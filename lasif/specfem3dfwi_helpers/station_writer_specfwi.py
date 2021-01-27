import os
import pandas as pd
import numpy as np

class StationWriterSpecFwi():
    """
    a class which
    - extracts station information for specified event
    - writeout one single STATION file for each event

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
        self.iteration = self.comm.iterations.get(iteration_name)

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

        # get selected waveform data
        processing_tag = self.iteration.processing_tag
        try:
            waveforms = self.comm.waveforms.get_metadata_processed(event_name, processing_tag)
        except:
            print("error while searching waveform data.")
            print("this error may be caused by no preprocessed signals in a event directory.")
            return None

        # store valid stations for the selected preprocess
        valid_st = []
        for waveform in waveforms:
            valid_st.append(waveform['network']+"."+waveform['station'])

        # reformat station dictionary for outputting in SPECFEM format
        station = []
        network = []
        latitude = []
        longitude = []
        elevation = []
        burial = []

        for a_st in stations:
            st_name = a_st.split(".")[1]
            net_name = a_st.split(".")[0]
            if net_name+"."+st_name in valid_st:
                st = stations[a_st]
                station.append(st_name)
                network.append(net_name)
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
        st_dir = os.path.join(self.outdir,"STATIONS_FILES")
        if not os.path.exists(st_dir):
            os.makedirs(st_dir)
        df.to_csv(os.path.join(st_dir,"STATIONS_"+event_name),sep=" ", index=False, header=False)
