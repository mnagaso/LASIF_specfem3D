import os
import obspy

class CmtWriterSpecFwi():
    """
    convert quakeml file to cmtsolution
    """

    def __init__(self, comm, iteration_name):
        # initialize the output file
        self.comm = comm
        self.outdir = os.path.join(self.comm.project.paths["output"],iteration_name)
        status = self.comm.query.get_iteration_status(iteration_name)

        # loop over events
        for event in sorted(status.keys()):
            self._write(event)

    def _write(self, event_name):
        # read QuakeML file in EVENTS
        qml_file = os.path.join(self.comm.project.paths["events"],event_name+".xml")
        ev = obspy.read_events(qml_file)
        # write out in CMTSOLUTION format
        cmt_file = os.path.join(self.outdir,"CMTSOLUTION_"+event_name)
        ev[0].write(cmt_file,format="cmtsolution")