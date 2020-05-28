import os
import datetime
import obspy, obspyh5
from obspy.geodetics.base import locations2degrees
from obspy.taup import TauPyModel
earth_model = TauPyModel("ak135")


class WavedataWriter():
    """
    write a waveform data in hdf5 format
    for SPECFEM3D_FWI input
    """

    def __init__(self, comm, iteration_name, window_margin, window_length):
        self.comm = comm
        self.outdir = os.path.join(self.comm.project.paths["output"],iteration_name)
        self.window_margin = window_margin
        self.window_length = window_length
        status = self.comm.query.get_iteration_status(iteration_name)

        # store some info for PySpecfem setup file
        self.tr_info = {}

        # loop over events
        for event in sorted(status.keys()):
            outfile = os.path.join(self.outdir,"waveform_"+event+".h5")
            self._write(outfile, event, iteration_name)
            print(outfile,"written")

    def _write(self, outfile, event_name, iteration_name):
        # Get event and iteration infos
        event = self.comm.events.get(event_name)
        iteration = self.comm.iterations.get(iteration_name)
        pparam = iteration.get_process_params()
        processing_tag = iteration.processing_tag

        # Get station and waveform infos
        station_coordinates = self.comm.query.get_all_stations_for_event(event_name)
        waveforms = self.comm.waveforms.get_metadata_processed(event_name, processing_tag)
        ## select waveforms for requested components:
        #waveforms = [wav for wav in waveforms
        #             if wav["channel"][-1] in components]

        # Group by station name.
        def func(x):
            return ".".join(x["channel_id"].split(".")[:2])
        waveforms.sort(key=func)

        # store all waveform in a obspy stream object
        st = obspy.Stream()
        for waveform in waveforms:
            st+=obspy.read(waveform['filename'])

        # calculate the fastest arrival time of initial wave
        # reached at any corner point of the target domain
        fastest_arrv = self._calculate_fastest_arrival(event_name)
        datetime_fastest = st[0].stats.starttime + datetime.timedelta(seconds=fastest_arrv)

        # cut timewindow
        st_cut = st.slice(datetime_fastest-datetime.timedelta(seconds=self.window_margin),
                          datetime_fastest+datetime.timedelta(seconds=self.window_length))

        # store windowed trace information for each event
        self.tr_info[event_name] = {'time_length':st_cut[0].stats.delta*st_cut[0].count(),
                                    'time_step':st_cut[0].stats.delta,
                                    'time_begin':fastest_arrv-self.window_margin,
                                    'time_end':  fastest_arrv-self.window_margin+self.window_length}

        obspyh5.writeh5(st_cut,outfile)


    def _calculate_fastest_arrival(self,event_name):
        """
        calculate the arrival times of event wave
        at four corners of the target domain
        then return the earliest time
        """
        event = self.comm.events.get(event_name)

        # get the coordinates of 4 domain corners
        domain = self.comm.project.domain
        four_corns = [[domain.min_latitude,domain.min_longitude],
                      [domain.min_latitude,domain.max_longitude],
                      [domain.max_latitude,domain.min_longitude],
                      [domain.max_latitude,domain.max_longitude]] # lat,lon

        # calculate epicentral distances
        distances = []
        for one_corn in four_corns:
            distances.append(locations2degrees(
                event["latitude"],event["longitude"],
                one_corn[0],one_corn[1]
            ))

        # calculate arrival times
        Phase = self.comm.project.config["download_settings"]["phase_of_interest"]
        tts = []
        for one_dist in distances:
            tt = earth_model.get_travel_times(source_depth_in_km=event["depth_in_km"],
                                               distance_in_degree=one_dist,
                                               phase_list=[Phase])
            tts.append(tt[0].time)

        return min(tts)