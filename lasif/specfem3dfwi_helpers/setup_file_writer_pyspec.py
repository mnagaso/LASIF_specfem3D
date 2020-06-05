import os

class PySpeSetupWriter():
    """
    """

    def __init__(self,comm,iteration_name, tr_info):
        """
        output a setup file of PySpecfem
        Not all parameters are automatically configured,
        thus it will necessary to modify before running
        PySpecfem command.
        """
        # get necessary information
        self.comm = comm
        self.iteration_name = iteration_name
        self.outfile = os.path.join(self.comm.project.paths["output"],self.iteration_name,"setup_file.in")
        domain = self.comm.project.domain
        # get event name lists
        status = self.comm.query.get_iteration_status(self.iteration_name)

        # setup input parameters
        self.LONGITUDE_CENTER_OF_CHUNK=(domain.min_longitude+domain.max_longitude)/2.0
        self.LATITUDE_CENTER_OF_CHUNK =(domain.min_latitude+domain.max_latitude)/2.0

        self.LONGITUDE_EXTENTION = (domain.max_longitude-domain.min_longitude)/2.0
        self.LATITUDE_EXTENTION  = (domain.max_latitude-domain.min_latitude)/2.0

        self.VERTICAL_EXTENTION = domain.max_depth_in_km - domain.min_depth_in_km
        self.AZIMUTH_OF_CHUNK = domain.rotation_angle_in_degree

        # warning if rotation axis is not [0,0,1]
        if domain.rotation_axis != [0.,0.,1.]:
            print("rotatoin_angle_in_degree in config.xml is understood as the rotation around Z axis.")
        self.DEPTH_OF_CHUNK = domain.min_depth_in_km

        # calculate the element size
        # initial value is decided by the lowpass period of the target iteration
        self.SIZE_EL_IN_KM = self._get_element_size()

        # AxiSEM dominant period
        self.DOMINANT_PERIOD = self._get_dominant_period()

        # initialize string objects
        self.TIME_BEGIN=""
        self.TIME_END=""
        self.CMT_file_string=""
        self.STATION_file_string=""

        # loop over events
        for i_ev, event in enumerate(sorted(status.keys())):
            if i_ev == 0:
                # SPECFEM time step settings
                self.time_length = tr_info[event]['time_length']
                self.time_step = tr_info[event]['time_step']
                self.time_step_data = tr_info[event]['time_step'] * 2 # should be configured mannually

            # start/end time of SPECFEM calculation window in second (0 at event time)
            self.TIME_BEGIN += " "+str(tr_info[event]['time_begin'])
            self.TIME_END   += " "+str(tr_info[event]['time_end'])

            # CMT file list
            self.CMT_file_string += "CMT_SOLUTION_FILE : CMTSOLUTION_{}\n".format(event)

            # STATION file list
            self.STATION_file_string+= "STATION_FILE : STATIONS_{}\n".format(event)


        # write out
        self._create_string()
        self._write()

    def _get_dominant_period(self):
        it = self.comm.iterations.get(self.iteration_name)
        dp = it.data_preprocessing["lowpass_period"] # get lowpass period as a dominant period for AxiSEM
        return dp

    def _get_element_size(self):
        it = self.comm.iterations.get(self.iteration_name)
        lowpass_period = it.data_preprocessing["lowpass_period"]
        #  a lowest wave speed in the target domain
        vs_slow = 3.8 # km/s
        # propose 1 spectral element par 1 wave length
        ds = vs_slow*lowpass_period/2.0
        return ds

    def _write(self):
        with open(self.outfile,"w") as f:
            f.write(self.outstr)

    def _create_string(self):

        self.outstr=f"""
#################################################################
#                                                               #
#                                                               #
#                    Domain for specfem                         #
#                                                               #
#               meshing Chunk with meshfem                      #
#                                                               #
#                                                               #
#                                                               #
#################################################################

#----------------------------------------------------------------
# Important : the following format is used :
#
#  KEYNAME : VALUE
#        >- -< space on both sides
#  need to have space before ":" and also after ":"
#  otherwise the VAKUE will wrong
#
#  line begins with "#" is a commment and will not
#  take into account
#----------------------------------------------------------------

# use coupling specfem and axisem
axisem_coupling : 1
model_type : ak135

# -----------------------------------------------------
#  Domain in spherical coordiantes
#  since axisem use geocentric coordiantes
#  we assume that the following values are
#  given in geocentric coordinates.

# center of domain lat, lon  (decimal degrees)
LONGITUDE_CENTER_OF_CHUNK : {self.LONGITUDE_CENTER_OF_CHUNK}
LATITUDE_CENTER_OF_CHUNK : {self.LATITUDE_CENTER_OF_CHUNK}

# extention of chunk before rotation (decimal degrees)
LONGITUDE_EXTENTION : {self.LONGITUDE_EXTENTION}
LATITUDE_EXTENTION : {self.LATITUDE_EXTENTION}

# vertical size (km)
VERTICAL_EXTENTION : {self.VERTICAL_EXTENTION}

# rotation of domain with respect to z axis in the center of domain
# given with respect to the north (0. means no rotation)
AZIMUTH_OF_CHUNK : {self.AZIMUTH_OF_CHUNK}

# depth for buried box (km)
# set 0. for domain that reach the free surface of the earth
DEPTH_OF_CHUNK : {self.DEPTH_OF_CHUNK}


#-------------------------------------------------------------
#
# topography file path  (comment to unuse it)
#   pyspecfem will automatically download ETOPO1 or SRTM15_PLUS file from NOAA server if not found at the specified path.
#
#ETOPO1 :  /home/mnagaso/workspace/Cheese_project/specfem_core_inversion/specfem_fwi/EXAMPLES/small_HDF5_test/etopo1_ice_g_f4/etopo1_ice_g_f4.flt
#SRTM15_PLUS :  /home/mnagaso/workspace/Cheese_project/specfem_core_inversion/specfem_fwi/EXAMPLES/small_HDF5_test/topo15.grd



#------------------------------------------------------------
# discretization of domain
#

#  in km
SIZE_EL_LONGITUDE_IN_KM : {self.SIZE_EL_IN_KM}
SIZE_EL_LATITUDE_IN_KM  : {self.SIZE_EL_IN_KM}

# or in degrees
#SIZE_EL_LONGITUDE_IN_DEG : 0.9
#SIZE_EL_LATITUDE_IN_DEG  : 0.9

# depth
SIZE_EL_DEPTH_IN_KM : {self.SIZE_EL_IN_KM}

# doubling --------------
#
# TODO
#

#################################################################
#                                                               #
#                                                               #
#                    AXISEM CONFIG                              #
#                                                               #
#                                                               #
#################################################################
#--------------------------------------------------------
#
# background model used in axisem : ak135, iasp91, prem
#
#

#### BACKGROUND MODELS
EARTH_MODEL : ak135

# Dominant period [s]
DOMINANT_PERIOD : {self.DOMINANT_PERIOD}


# MPI decomposition for AXISEM
NTHETA_SLICES :  8
NRADIAL_SLICES : 2

#################################################################
#                                                               #
#                                                               #
#                 SOURCES - RECEIVERS                           #
#                                                               #
#                                                               #
#################################################################

# path to CMT solution file (format from specfem)
{self.CMT_file_string}

# path to station file (format :
# station_name  network_name latitue(deg) longitude(deg) elevation(m) buried(m)
station_type : geo_file
{self.STATION_file_string}

#################################################################
#                                                               #
#                                                               #
#                   SPECFEM CONFIG                              #
#                                                               #
#                                                               #
#################################################################

# MPI decomposition for SPECFEM
number_of_mpi_domain : 1

# simulation time sampling
time_length : {self.time_length}
time_step : {self.time_step}
time_step_data : {self.time_step_data}

# GPU mode
use_gpu : 1

#################################################################
#                                                               #
#                                                               #
#                   COUPLING CONFIG                             #
#                                                               #
#                                                               #
#################################################################

TIME_BEGIN : {self.TIME_BEGIN}
TIME_END   : {self.TIME_END}
#################################################################
#                                                               #
#                                                               #
#                       PATHS                                   #
#                                                               #
#                                                               #
#################################################################
#-------
# PATH TO SPECFEM DIRECTORY
specfem_directory : /home/mnagaso/workspace/Cheese_project/specfem_core_inversion/specfem_fwi
AXISEM_COUPLING_DIR : /home/mnagaso/workspace/Cheese_project/specfem_core_inversion/specfem_fwi/src/extern_packages/coupling/


#--

#################################################################
#                                                               #
#                                                               #
#                       SCRIPTS                                 #
#                                                               #
#                                                               #
#################################################################
#
# todo choice beteween script for different clusters
#
script_type : default
use_inverse_problem : 1

mpirun_command : mpirun.mpich
hdf5_enabled : 1
number_of_io_node : 2
"""