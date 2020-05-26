import os,h5py
from lasif.components.component import Component

class StationWriterSpecFwi(Component):
    """
    a class which
    - extracts station information for specified event
    - writeout one single hdf5 STATION file storing all station of all events

    the composition of output file is:

    stations_fwi.h5/EVENTNAME_0/station
                              /network
                              /latitude (deg)
                              /longitude (deg)
                              /elevation (m)
                              /burial (m)
                   /EVENTNAME_1/...
                   ...

    """
    def __init__(self,comm,iteration_name):
        # initialize the output file
        self.comm = comm
        outdir = os.path.join(self.comm.project.paths["output"],iteration_name)
        # create iteration directory in OUTPUT
        try:
            os.makedirs(outdir)
        except OSError:
            if not os.path.isdir(outdir):
                raise
        self.outfile = os.path.join(outdir,"stations_fwi.h5")

        status = self.comm.query.get_iteration_status(iteration_name)
        # create file
        with h5py.File(self.outfile,"w") as f:
            print("creating a station file at ",self.outfile)

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

        print(stations)