import os
import obspy

class CmtWriterSpecFwi():
    """
    convert quakeml file to cmtsolution
    """

    def __init__(self, comm, iteration_name):
        # initialize the output file
        self.comm = comm
        self.iteration = self.comm.iterations.get(iteration_name)
        self.outdir = os.path.join(self.comm.project.paths["output"],iteration_name)
        status = self.comm.query.get_iteration_status(iteration_name)

        # loop over events
        for event in sorted(status.keys()):
            self._write(event)

    def _write(self, event_name):
        # check if the event has any available preprocessed signals
        processing_tag = self.iteration.processing_tag
        try:
            waveforms = self.comm.waveforms.get_metadata_processed(event_name, processing_tag)
        except:
            print("error while searching waveform data.")
            print("this error may be caused by no preprocessed signals in a event directory.")
            return None


        # read QuakeML file in EVENTS
        qml_file = os.path.join(self.comm.project.paths["events"],event_name+".xml")
        ev = obspy.read_events(qml_file)

        # write out in CMTSOLUTION format
        cmt_dir = os.path.join(self.outdir,"CMTSOLUTION_FILES")
        if not os.path.exists(cmt_dir):
            os.makedirs(cmt_dir)
        cmt_file = os.path.join(cmt_dir,"CMTSOLUTION_"+event_name)
        ev[0].write(cmt_file,format="cmtsolution")