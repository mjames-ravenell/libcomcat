#!/usr/bin/env python
import argparse
import sys
import logging
from datetime import timedelta


import libcomcat
from libcomcat.search import search, count
from libcomcat.utils import (maketime, check_ccode,
                             get_country_bounds, filter_by_country,
                             BUFFER_DISTANCE_KM, CombinedFormatter)
from libcomcat.dataframes import (get_detail_data_frame,
                                  get_summary_data_frame)
from libcomcat.logging import setup_logger


def get_parser():
    desc = '''Download basic earthquake information in line format (csv, tab, etc.).

    To download basic event information (time,lat,lon,depth,magnitude) and
    moment tensor components for a box around New Zealand during 2013:

    %(prog)s nz.csv -b 163.213 -178.945 -48.980 -32.324 -s 2013-01-01 -e 2014-01-01 -f csv

    To expand the results to include preferred moment tensors:

    %(prog)s nz.xlsx -o preferred -b 163.213 -178.945 -48.980 -32.324 -s 2013-01-01 -e 2014-01-01 -f excel

    To expand the results to include ALL moment tensors:

    %(prog)s nz.xlsx -o all -b 163.213 -178.945 -48.980 -32.324 -s 2013-01-01 -e 2014-01-01 -f excel

    To expand the results to include preferred focal mechanisms:

    %(prog)s nz.xlsx -a preferred -b 163.213 -178.945 -48.980 -32.324 -s 2013-01-01 -e 2014-01-01 -f excel

    To expand the results to include ALL focal mechanisms:

    %(prog)s nz.xlsx -a all -b 163.213 -178.945 -48.980 -32.324 -s 2013-01-01 -e 2014-01-01 -f excel

    To include all magnitudes (including source and type) for that same search, add the -g flag:

    %(prog)s nz.csv -o -b 163.213 -178.945 -48.980 -32.324 -s 2013-01-01 -e 2014-01-01 -g -f csv

    To print the number of events that would be returned from the above query,
    and the maximum number of events supported by ONE ComCat query*:

    %(prog)s tmp.csv -x -o -b 163.213 -178.945 -48.980 -32.324 -s 2013-01-01 -e 2014-01-01

    To download events with fractional days, use the ISO 8601 combined date
    time format (YYYY-mm-ddTHH:MM:SS, YYYY-mm-ddTHH:MM:SS.s): %(prog)s -s
    2015-01-01T00:00:00 -e 2015-01-01T01:15:00

    NOTES:

    Any start or end time where only date is specified (YYYY-mm-dd) will
    be translated to the beginning of that day.  Thus, a start time of
    "2015-01-01" becomes "2015-01-01T:00:00:00" and an end time of "2015-01-02"
    becomes ""2015-01-02T:00:00:00".

    Events which do not have a value for a given field (moment tensor
    components, for example), will have the string "nan" instead.

    Note that when specifying a search box that crosses the -180/180 meridian,
    you simply specify longitudes as you would if you were not crossing that
    meridian (i.e., lonmin=179, lonmax=-179).  The program will resolve the
    discrepancy.

    When specifying the -a or -o flags, whether "preferred" or "all",
    a new column will be added for each different source and algorithm
    used to create the moment tensor or focal mechanism.  For example,
    columns containing NEIC W-phase moment tensor solution information
    should be prepended by "us_Mww" (network_method) to distinguish
    them from, say "nc_mwr" (Northern California regional moment
    tensor).  If "all" is chosen, then there will be many such columns
    of information, each prepended with the network and method, WHERE
    SUCH METHOD IS AVAILABLE IN THE DATABASE.

    The ComCat API has a returned event limit of 20,000.  Queries that
    exceed this ComCat limit ARE supported by this software, by
    breaking up one large request into a number of smaller ones.
    However, large queries, when also configured to retrieve moment
    tensor parameters, nodal plane angles, or moment tensor type can
    take a very long time to download. This delay is caused by the
    fact that when this program has to retrieve moment tensor
    parameters, nodal plane angles, or moment tensor type, it must
    open a URL for EACH event and parse the data it finds.  If these
    parameters are not requested, then the same request will return in
    much less time (~10 minutes or less for a 20,000 event query).
    Queries for all magnitude solutions will take even more time, as
    this requires parsing an XML file for each event and extracting
    the magnitude values and associated source and type.  '''

    parser = argparse.ArgumentParser(
        description=desc, formatter_class=CombinedFormatter)
    # positional arguments
    parser.add_argument('filename',
                        metavar='FILENAME', help='Output filename.')
    # optional arguments
    parser.add_argument('--version', action='version',
                        version=libcomcat.__version__)
    helpstr = ('Bounds to constrain event search '
               '[lonmin lonmax latmin latmax]')
    parser.add_argument('-b', '--bounds',
                        metavar=('lonmin', 'lonmax', 'latmin', 'latmax'),
                        dest='bounds', type=float, nargs=4,
                        help=helpstr)

    country_str = '''Specify three character country code and earthquakes
    from inside country polygon (50m resolution) will be returned. Earthquakes
    in the ocean likely will NOT be returned.

    See https://en.wikipedia.org/wiki/List_of_ISO_3166_country_codes
    '''
    parser.add_argument('--country', help=country_str)

    buffer_str = '''Use in conjunction with --country. Specify a buffer in km
    around country border where events will be selected.
    '''
    parser.add_argument('--buffer', help=buffer_str,
                        type=int, default=BUFFER_DISTANCE_KM)

    helpstr = 'Search radius in KM (use instead of bounding box)'
    parser.add_argument('-r', '--radius', dest='radius',
                        metavar=('lat', 'lon', 'rmax'),
                        type=float, nargs=3,
                        help=helpstr)
    helpstr = ('Start time for search (defaults to ~30 days ago). '
               'YYYY-mm-dd, YYYY-mm-ddTHH:MM:SS, or YYYY-mm-ddTHH:MM:SS.s')
    parser.add_argument('-s', '--start-time', dest='startTime', type=maketime,
                        help=helpstr)
    helpstr = ('End time for search (defaults to current date/time). '
               'YYYY-mm-dd, YYYY-mm-ddTHH:MM:SS, or YYYY-mm-ddTHH:MM:SS.s')
    parser.add_argument('-e', '--end-time', dest='endTime', type=maketime,
                        help=helpstr)

    helpstr = ('Number of days after start time (instead of end time). ')
    parser.add_argument('--numdays', dest='numdays', type=int,
                        help=helpstr)

    helpstr = ('Limit to events after specified time. YYYY-mm-dd or '
               'YYYY-mm-ddTHH:MM:SS')
    parser.add_argument('-t', '--time-after', dest='after', type=maketime,
                        help=helpstr)
    helpstr = 'Min/max (authoritative) magnitude to restrict search.'
    parser.add_argument('-m', '--mag-range', metavar=('minmag', 'maxmag'),
                        dest='magRange', type=float, nargs=2,
                        help=helpstr)
    helpstr = ('Source catalog from which products '
               'derive (atlas, centennial, etc.)')
    parser.add_argument('-c', '--catalog', dest='catalog',
                        help=helpstr)
    helpstr = 'Source contributor (who loaded product) (us, nc, etc.)'
    parser.add_argument('-n', '--contributor', dest='contributor',
                        help=helpstr)

    helpstr = ('Extract preferred or all moment-tensor components '
               '(including type and derived hypocenter) where available.')
    parser.add_argument('-o', '--get-moment-components',
                        dest='getComponents',
                        choices=['none', 'preferred', 'all'],
                        default='none',
                        help=helpstr)
    helpstr = ('Extract preferred or all focal-mechanism angles '
               '(strike,dip,rake) where available.')
    parser.add_argument('-a', '--get-focal-angles',
                        dest='getAngles', choices=['none', 'preferred', 'all'],
                        default='none',
                        help=helpstr)

    helpstr = ('Extract moment tensor supplemental information '
               '(duration, derived origin, percent double couple) '
               'when available.')
    parser.add_argument('--get-moment-supplement',
                        dest='getMomentSupplement', action='store_true',
                        help=helpstr)

    helpstr = ('Extract all magnitudes (with sources), '
               'authoritative listed first.')
    parser.add_argument('-g', '--get-all-magnitudes',
                        dest='getAllMags', action='store_true',
                        help=helpstr)
    parser.add_argument('-f', '--format', dest='format',
                        choices=['csv', 'tab', 'excel'], default='csv',
                        metavar='FORMAT', help='Output format.')

    helpstr = ('Limit the search to only those events containing '
               'products of type PRODUCT. See the full list here: '
               'https://usgs.github.io/pdl/userguide/products/index.html')

    parser.add_argument('-p', '--product-type',
                        dest='limitByProductType', metavar='PRODUCT',
                        help=helpstr)
    helpstr = 'Just return the number of events in search and maximum allowed.'
    parser.add_argument('-x', '--count', dest='getCount',
                        action='store_true',
                        help=helpstr)
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='Print progress')
    helpstr = ('Specify a different comcat *search* host than '
               'earthquake.usgs.gov.')
    parser.add_argument('--host',
                        help=helpstr)

    helpstr = """Limit to events with a specific PAGER alert level. The allowed values are:
              - green; Limit to events with PAGER alert level "green".
              - yellow; Limit to events with PAGER alert level "yellow".
              - orange; Limit to events with PAGER alert level "orange".
              - red; Limit to events with PAGER alert level "red"."""
    parser.add_argument('--alertlevel', help=helpstr, default=None)

    loghelp = '''Send debugging, informational, warning and error messages to a file.
    '''
    parser.add_argument('--logfile', default='stderr', help=loghelp)
    levelhelp = '''Set the minimum logging level. The logging levels are (low to high):

     - debug: Debugging message will be printed, most likely for developers.
              Most verbose.
     - info: Only informational messages, warnings, and errors will be printed.
     - warning: Only warnings (i.e., could not retrieve information for a
                single event out of many) and errors will be printed.
     - error: Only errors will be printed, after which program will stop.
              Least verbose.
    '''
    parser.add_argument('--loglevel', default='info',
                        choices=['debug', 'info', 'warning', 'error'],
                        help=levelhelp)
    return parser


def main():
    parser = get_parser()
    args = parser.parse_args()

    # make sure we don't have -e option AND --numdays option
    if args.endTime is not None and args.numdays is not None:
        msg = ('You must specify end time or number of days since '
               'start time, not both. Exiting.')
        print(msg)
        sys.exit(1)

    if not args.endTime and args.numdays:
        args.endTime = args.startTime + timedelta(args.numdays)

    setup_logger(args.logfile, args.loglevel)

    tsum = (args.bounds is not None) + \
        (args.radius is not None) + (args.country is not None)
    if tsum != 1:
        logging.error(
            'Please specify a bounding box, radius, or country code.')
        sys.exit(1)

    latitude = None
    longitude = None
    radiuskm = None
    lonmin = latmin = lonmax = latmax = None
    bounds = None
    if args.radius:
        latitude = args.radius[0]
        longitude = args.radius[1]
        radiuskm = args.radius[2]

    if args.bounds:
        lonmin, lonmax, latmin, latmax = args.bounds
        # fix longitude bounds when crossing dateline
        if lonmin > lonmax and lonmax >= -180:
            lonmin -= 360
    else:
        lonmin, lonmax, latmin, latmax = None, None, None, None
        bounds = (lonmin, lonmax, latmin, latmax)

    if args.country:
        ccode = args.country
        if not check_ccode(ccode):
            curl = 'https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2'
            fmt = ('%s is not a valid ISO 3166 country code. '
                   'See %s for the list.')
            tpl = (ccode, curl)
            logging.error(fmt % tpl)
            sys.exit(1)
        bounds = get_country_bounds(ccode, args.buffer)  # this returns a list

    minmag = 0.0
    maxmag = 9.9
    if args.magRange:
        minmag = args.magRange[0]
        maxmag = args.magRange[1]

    if args.getCount:
        if isinstance(bounds, tuple) or bounds is None:
            nevents = count(starttime=args.startTime,
                            endtime=args.endTime,
                            updatedafter=args.after,
                            minlatitude=latmin,
                            maxlatitude=latmax,
                            minlongitude=lonmin,
                            maxlongitude=lonmax,
                            latitude=latitude,
                            longitude=longitude,
                            maxradiuskm=radiuskm,
                            catalog=args.catalog,
                            contributor=args.contributor,
                            maxmagnitude=maxmag,
                            minmagnitude=minmag,
                            producttype=args.limitByProductType,
                            verbose=args.verbose)
        else:
            for lonmin, lonmax, latmin, latmax in bounds:
                nevents = 0
                nevents += count(starttime=args.startTime,
                                 endtime=args.endTime,
                                 updatedafter=args.after,
                                 minlatitude=latmin,
                                 maxlatitude=latmax,
                                 minlongitude=lonmin,
                                 maxlongitude=lonmax,
                                 latitude=latitude,
                                 longitude=longitude,
                                 maxradiuskm=radiuskm,
                                 catalog=args.catalog,
                                 contributor=args.contributor,
                                 maxmagnitude=maxmag,
                                 minmagnitude=minmag,
                                 producttype=args.limitByProductType,
                                 verbose=args.verbose)
        print('There are %i events matching input criteria.' % nevents)
        sys.exit(0)
    if isinstance(bounds, tuple) or bounds is None:
        events = search(starttime=args.startTime,
                        endtime=args.endTime,
                        updatedafter=args.after,
                        minlatitude=latmin,
                        maxlatitude=latmax,
                        minlongitude=lonmin,
                        maxlongitude=lonmax,
                        latitude=latitude,
                        longitude=longitude,
                        maxradiuskm=radiuskm,
                        catalog=args.catalog,
                        contributor=args.contributor,
                        maxmagnitude=maxmag,
                        minmagnitude=minmag,
                        producttype=args.limitByProductType,
                        host=args.host,
                        verbose=args.verbose,
                        alertlevel=args.alertlevel)
    else:
        events = []
        for i, tbounds in enumerate(bounds):
            lonmin, lonmax, latmin, latmax = tbounds
            fmt = 'Checking bounds %i of %i for %s...\n'
            tpl = (i + 1, len(bounds), ccode)
            logging.debug(fmt % tpl)
            tevents = search(starttime=args.startTime,
                             endtime=args.endTime,
                             updatedafter=args.after,
                             minlatitude=latmin,
                             maxlatitude=latmax,
                             minlongitude=lonmin,
                             maxlongitude=lonmax,
                             latitude=latitude,
                             longitude=longitude,
                             maxradiuskm=radiuskm,
                             catalog=args.catalog,
                             contributor=args.contributor,
                             maxmagnitude=maxmag,
                             minmagnitude=minmag,
                             producttype=args.limitByProductType,
                             host=args.host,
                             verbose=args.verbose,
                             alertlevel=args.alertlevel)
            events += tevents

    if not len(events):
        logging.info('No events found matching your search criteria. Exiting.')
        sys.exit(0)

    if (args.getAngles != 'none' or
            args.getAllMags or
            args.getComponents != 'none'):

        logging.info(
            'Fetched %i events...creating table.\n' % (len(events)))
        supp = args.getMomentSupplement
        df = get_detail_data_frame(events, get_all_magnitudes=args.getAllMags,
                                   get_tensors=args.getComponents,
                                   get_focals=args.getAngles,
                                   get_moment_supplement=supp,
                                   verbose=args.verbose)
    else:
        logging.info(
            'Fetched %i events...creating summary table.\n' % (len(events)))
        df = get_summary_data_frame(events)

    # order the columns so that at least the initial parameters come the way
    # we want them...
    first_columns = list(events[0].toDict().keys())
    col_list = list(df.columns)
    for column in first_columns:
        col_list.remove(column)
    df = df[first_columns + col_list]

    if args.country:
        df = filter_by_country(df, ccode, buffer_km=args.buffer)

    logging.info('Created table...saving %i records to %s.\n' %
                 (len(df), args.filename))
    if args.format == 'csv':
        df.to_csv(args.filename, index=False, chunksize=1000)
    elif args.format == 'tab':
        df.to_csv(args.filename, sep='\t', index=False)
    else:
        df.to_excel(args.filename, index=False)
    logging.info('%i records saved to %s.' % (len(df), args.filename))
    sys.exit(0)


if __name__ == '__main__':
    main()
