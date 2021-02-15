#!/usr/bin/env python
# -*- coding: utf-8 -*-

# NIED version function of MassDownloader (obspy.client.fdsn.mass_downloader)
# used at
# lasif.components.downloads DownloadsComponent.donwload_data_for_one_evnt

import os, datetime, getpass, glob, shutil
import obspy
from obspy.clients.fdsn.mass_downloader import GlobalDomain
from obspy import UTCDateTime

from HinetPy import Client, win32
import keyring

from lasif.nied_manager.nied_filehandler import *

service_id = "yOhiUCGXdVIjPINGJ1J0"
MAGIC_USERNAME_KEY = "9ug5xNtF3QDnT9voMjWf"

class NiedDownloader():
    """
    download manager for seismic data provided by NIED
    To use this class, login account for accessing NIED server is required.
    win32tools is also required for converting win32 format to SAC PZ.

    network name for NIED should be "NIED.0101" (NIED. + station code)
    """

    def __init__(self,starttime=None,endtime=None,network=None,stations=None,
                      domain=None):
        self.starttime    = starttime
        self.endtime      = endtime
        self.network      = network.split(",")
        self.domain       = domain
        self.outdir       = "./test_nied_lasif" # debug

        # time values in JST
        self.starttime_JST = self.starttime + datetime.timedelta(hours=9)
        self.endtime_JST   = self.endtime + datetime.timedelta(hours=9)

        login_ok = None
        self.client = Client(retries=5,sleep_time_in_seconds=10)

        # authentication for NIED server
        while(login_ok == None):
            try:
                user = keyring.get_password(service_id, MAGIC_USERNAME_KEY)
                pswd = keyring.get_password(service_id, user)
                self.client.login(user,pswd)
                login_ok=1
            except:
                user = input("Username: ")
                pswd = getpass.getpass("Password: ")

                keyring.set_password(service_id, user, pswd)
                keyring.set_password(service_id, MAGIC_USERNAME_KEY, user)

                try:
                    self.client.login(user,pswd)
                    login_ok=1
                except:
                    pass


        # select stations from domain boundary
        for network in self.network:
            network_code = network.lstrip("NIED.")
            print("downloading NIED network-{} data".format(network_code))
            if self.domain.__class__.__name__ == "SphericalSectionDomain":
                params = self.domain.get_query_parameters()
                self.client.select_stations(network_code,
                                                latitude =params["latitude"],
                                                longitude=params["longitude"],
                                                maxradius=params["maxradius"])
            else:
                self.client.select_stations(network_code, minlatitude=self.domain.min_latitude,
                                                maxlatitude =self.domain.max_latitude,
                                                minlongitude=self.domain.min_longitude,
                                                maxlongitude=self.domain.max_longitude)

            if (stations != None):
                # select stations by name
                self.client.select_stations(network_code,stations.split(','))

    def download(self, outdir=None, stationdir=None):
        self.outdir    =outdir
        self.stationdir=stationdir

        # download waveform
        for network in self.network:
            network_code = network.lstrip("NIED.")
            output_dir   = os.path.join(self.outdir,network_code)
            span         = int((self.endtime_JST-self.starttime_JST)/60.0) # in minutes
            data, ctable = self.client.get_continuous_waveform(network_code,self.starttime_JST.datetime,span,outdir=output_dir)

        # convert waveform file format
        try:
            self.convert_format()
        except:
            pass

        # make symlinks of SACPZ files in Station/SACPZ
        sacs = glob.glob(self.outdir+"/*.SAC")
        pzs  = glob.glob(self.outdir+"/*.SAC_PZ")

        # filtering the stations outside the target boundary
        # as S-net downloader downloads wave data from all stations
        for sac in sacs:
            try:
                st=obspy.read(sac)
                stat=st[0].stats
                st_lon = stat.sac.stlo
                st_lat = stat.sac.stla

                if st_lon < self.domain.min_longitude + self.domain.boundary_width_in_degree or \
                   st_lon > self.domain.max_longitude - self.domain.boundary_width_in_degree or \
                   st_lat < self.domain.min_latitude  + self.domain.boundary_width_in_degree or \
                   st_lat > self.domain.max_latitude  - self.domain.boundary_width_in_degree:
                   os.remove(sac)
            except:
                pass

        # get new sac file list
        sacs = glob.glob(self.outdir+"/*.SAC")
        pzs  = glob.glob(self.outdir+"/*.SAC_PZ")

        # modify the timezone in sac files and overwrite
        # change the component name for LASIF
        # for MeSO net, those SAC files do not include the network name, so add here those network name
        for sac in sacs:
            try: # skip broken files
                st=obspy.read(sac)
                st[0].stats.starttime+=datetime.timedelta(hours=-9)
                # add nied network name in sac file
                if st[0].stats.sac.kevnm != '':
                    st[0].stats.network = st[0].stats.sac.kevnm
                elif st[0].stats.station.startswith('N.S'):
                    st[0].stats.network = 'S-Net'
                else: # for MeSO
                    st[0].stats.network = 'MeSO-Net'
                    st[0].stats.sac.kevnm = 'MeSO-Net'

                # replace . in station name with _
                st[0].stats.station = st[0].stats.station.replace('.','_')

                # change component name
                st[0].stats.sac.kcmpnm = channel_name_converter_for_NIED2LASIF(st[0].stats.sac.kcmpnm)
                st[0].stats.channel = channel_name_converter_for_NIED2LASIF(st[0].stats.channel)

                st.write(sac)

                # modify the filename
                sep=sac.split(".")
                sep[-2] = channel_name_converter_for_NIED2LASIF(sep[-2])
                sac_mod = ".".join(x for x in sep)
                os.rename(sac,sac_mod)
            except:
                pass

        for sac in sacs:
            try: # make hardlink if not exits
                # modify the filename
                sep=sac.split(".")
                sep[-2] = channel_name_converter_for_NIED2LASIF(sep[-2])
                sac_mod = ".".join(x for x in sep)

                # here event name is added at the head of filename
                # to be found by station_cache registration process.
                link_name=self.outdir.split("/")[-2]+"_"+os.path.basename(sac_mod)
                print(link_name)
                os.link(sac_mod, os.path.join(stationdir,link_name))
            except:
                pass

        # pz files are replaced into the station files
        for pz in pzs:
            shutil.move(pz, os.path.join(stationdir,os.path.basename(pz)))

    def convert_format(self):
        network_dirs = [ f.path for f in os.scandir(self.outdir) if f.is_dir() ]

        for network_dir in network_dirs:
            datas   = sorted(glob.glob(network_dir+"/*.cnt"))
            ctables = sorted(glob.glob(network_dir+"/*.ch"))

            for j in range(len(datas)):
                data   = datas[j]
                ctable = ctables[j]

                # extract wave
                win32.extract_sac(data,ctable,outdir=self.outdir)
                # extract instrumental responses
                win32.extract_pz(ctable,outdir=self.outdir)

            # erase the win32 format datafile
            shutil.rmtree(network_dir)