import os
import pandas as pd
import numpy as np

class StationWriterSpecFwi():
    """
    a class which
    - extracts station information for specified event
    - writeout one singl STATION file for each event

    the composition of output file is:
    """

    def __init__(self,comm,iteration_name):
        # initialize the output file
        self.comm = comm
        self.outdir = os.path.join(self.comm.project.paths["output"],iteration_name)
        # create iteration directory in OUTPUT
        try:
            os.makedirs(self.outdir)
        except OSError:
            if not os.path.isdir(self.outdir):
                raise

        status = self.comm.query.get_iteration_status(iteration_name)

        # loop over events
        for event in sorted(status.keys()):
            self._write(event)


    def _write(self,event_name):
        """
        write station list of one event
        """

        try:
            stations = self.comm.query.get_all_stations_for_event(event_name)
        except LASIFError:
            stations = {}

        # reformat station dictionary for outputting in SPECFEM format
        station = []
        network = []
        latitude = []
        longitude = []
        elevation = []
        burial = []

        for a_st in stations:
            st = stations[a_st]
            station.append(a_st.split(".")[1])
            network.append(a_st.split(".")[0])
            latitude.append( st["latitude"])
            longitude.append(st["longitude"])
            elevation.append(st["elevation_in_m"])
            burial.append(   st["local_depth_in_m"])

        dict_stations={"station":station,
                       "network":network,
                       "latitude":latitude,
                       "longitude":longitude,
                       "elevation":elevation,
                       "burial":burial,
        }

        df = pd.DataFrame(dict_stations)
        # write
        df.to_csv(os.path.join(self.outdir,"STATIONS_"+event_name),sep=" ", index=False, header=False)
