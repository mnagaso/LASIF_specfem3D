#!/usr/bin/env python
# -*- coding: utf-8 -*-
import obspy, datetime

def simple_sacpz_parser(filename):
    """
    return a list of channels' dict for a given filename

    one dict must includes:
        channel_id,start_date,end_date,
        latitude,longitude,elevation_in_m,local_depth_in_m

    The datetime value in origina NIED SAC files are all in JST time (UTC + 9).
    This has already converted to GMT when downloaded.
    """

    channel = {}
    st = obspy.read(filename)
    stat = st[0].stats
    sac = st[0].stats.sac
    channel["channel_id"]       = "{}.{}.{}.{}".format(stat["network"],stat["station"],stat["location"],stat["channel"])
    #channel["channel_id"]       = "{}.{}.{}".format(stat["station"],stat["location"],stat["channel"])
    channel["start_date"]       = stat["starttime"]
    channel["end_date"]         = stat["endtime"]
    channel["latitude"]         = float(sac.stla)
    channel["longitude"]        = float(sac.stlo)
    channel["elevation_in_m"]   = float(sac.stel)
    channel["local_depth_in_m"] = 0.0

    return [channel]

def channel_name_converter_for_NIED2SPECFEM(c):
    if c == "VX": # NIED S-net
        r = "UX"
    elif c == "VY":
        r = "UY"
    elif c == "VZ":
        r = "UZ"
    elif c == "E": # NIED  Hi-net
        r = "UX"
    elif c == "N":
        r = "UY"
    elif c == "U":
        r = "UZ"
    elif c == "X":
        r = "UX"
    elif c == "Y":
        r = "UY"
    elif c == "Z":
        r = "UZ"
    elif c == "EB": # NIED F-net
        r = "UX"
    elif c == "NB":
        r = "UY"
    elif c == "UB":
        r = "UZ"
    else:
        print("component name {} is not recognised by wavedata_writer_specfwi.py".format(c))
        print("please add your rule into _conversion_rules")

    return r


def channel_name_converter_for_NIED2LASIF(c):
    if c == "VX": # NIED S-net
        r = "E"
    elif c == "VY":
        r = "N"
    elif c == "VZ":
        r = "Z"
    elif c == "E": # NIED  Hi-net
        r = "E"
    elif c == "N":
        r = "N"
    elif c == "U":
        r = "Z"
    elif c == "X":
        r = "E"
    elif c == "Y":
        r = "N"
    elif c == "EB": # NIED F-net
        r = "E"
    elif c == "NB":
        r = "N"
    elif c == "UB":
        r = "Z"

    elif c == "Z" or c == "N" or c == "E": # keep them
        r = c


    else:
        print("component name {} is not recognised by wavedata_writer_specfwi.py".format(c))
        print("please add your rule into _conversion_rules")

    #print("debug c2r", c, r)

    return r

