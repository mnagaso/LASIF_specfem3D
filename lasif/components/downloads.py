#!/usr/bin/env python
# -*- coding: utf-8 -*-


import copy
import logging
import numpy as np
import os

from lasif import rotations
import lasif.domain
from .component import Component


class DownloadsComponent(Component):
    """
    Component dealing with the station and data downloading.

    :param communicator: The communicator instance.
    :param component_name: The name of this component for the communicator.
    """
    def download_data(self, event_names=None, providers=None, networks=None):
        """
        Download waveforms and station info on a loop of events available in EVENTS
        MPI enabled
        """

        if event_names is None and (networks is None or not networks.startswith("NIED")):
            from mpi4py import MPI
            from lasif.tools.parallel_helpers import distribute_across_ranks
            events = self.comm.events.list()
            to_be_processed = []
            for event in events:
                event_dict = {"event": event,
                              "providers": providers,
                              "networks": networks}
                to_be_processed.append(event_dict)

            logfile = self.comm.project.get_log_file("DOWNLOADS", "all_events")

            # Only rank 0 needs to know what has to be processsed.
            if MPI.COMM_WORLD.rank == 0:
                event_to_download = to_be_processed
            else:
                event_to_download = None

            distribute_across_ranks(
                self.comm.downloads.download_data_for_one_event, items=event_to_download,
                get_name=lambda x: x["event"],
                logfile=logfile)
        if event_names is None and networks.startswith("NIED"):
            event_names = self.comm.events.list()
            for event in event_names:
                self.comm.downloads.download_data_for_one_event(event, providers=providers, networks=networks)
        else:
            for event in event_names:
                self.comm.downloads.download_data_for_one_event(event, providers=providers, networks=networks)


    def download_data_for_one_event(self, event, providers=None, networks = None):
        event = self.comm.events.get(event)

        from obspy.clients.fdsn.mass_downloader import \
            Restrictions, GlobalDomain

        print(" ")
        print(("######## Looking for data for "+event["event_name"]+" #########"))
        print(" ")

        proj = self.comm.project

        if isinstance(proj.domain, lasif.domain.GlobalDomain):
            domain = GlobalDomain()
        else:
            domain = self._get_spherical_section_domain(proj.domain)

        event_time = event["origin_time"]
        ds = proj.config["download_settings"]
        starttime = event_time - ds["seconds_before_event"]
        endtime = event_time + ds["seconds_after_event"]

        mseed_storage = os.path.join(proj.paths["data"], event["event_name"],
                                     "raw")

        # download from FDSN server
        if (networks is None or not networks.startswith("NIED")):
            from obspy.clients.fdsn.mass_downloader import MassDownloader

            print("download from FDSN server")

            # Attempt to get StationXML data for a very long time span. This has
            # the nice side effect that StationXML files will mostly be shared
            # between events.
            restrictions = Restrictions(
                starttime=starttime,
                endtime=endtime,
                # Go back 10 years.
                station_starttime=starttime - 86400 * 365.25 * 10,
                # Advance 10 years.
                station_endtime=endtime + 86400 * 365.25 * 10,
                network=networks, station=None, location=None, channel=None,
                minimum_interstation_distance_in_m=ds[
                    "interstation_distance_in_m"],
                reject_channels_with_gaps=True,
                minimum_length=0.95,
                location_priorities=ds["location_priorities"],
                channel_priorities=ds["channel_priorities"])

            stationxml_storage = self._get_stationxml_storage_fct(starttime,
                                                                  endtime)

            # Also log to file for reasons of provenance and debugging.
            logger = logging.getLogger("obspy.clients.fdsn.mass_downloader")
            fh = logging.FileHandler(
                self.comm.project.get_log_file("DOWNLOADS", event["event_name"]))
            fh.setLevel(logging.INFO)
            FORMAT = "[%(asctime)s] - %(name)s - %(levelname)s: %(message)s"
            formatter = logging.Formatter(FORMAT)
            fh.setFormatter(formatter)
            logger.addHandler(fh)

            dlh = MassDownloader(providers=providers)
            dlh.download(domain=domain, restrictions=restrictions,
                         mseed_storage=mseed_storage,
                         stationxml_storage=stationxml_storage)

        # download from NIED server
        else:
            from lasif.nied_manager.nied_downloader import NiedDownloader
            print("download from NIED server")

            dlh = NiedDownloader(starttime=starttime,
                                 endtime=endtime,
                                 network=networks,
                                 domain=proj.domain,
                                 )
            sacpaz_path=self.comm.project.paths["sacpz"]
            dlh.download(outdir=mseed_storage,stationdir=sacpaz_path)

        print("")

    def query_station_inventory(self, starttime, endtime):
        """
        Query stations inside the domain and store the inventory

        Parameters
        ----------
        starttime : obspy UTCDateTime
        endtime : obspy UTCDateTime

        Returns
        -------
        station inventory. Obspy Inventory class

        """
        from obspy.clients.fdsn import Client
        from obspy.clients.fdsn.header import URL_MAPPINGS
        from obspy.core.inventory import Inventory


        proj = self.comm.project
        #ds = proj.config["download_settings"]
        #channel_priorities=ds["channel_priorities"]

        if isinstance(proj.domain, lasif.domain.GlobalDomain):
            minlongitude = 0
            maxlongitude = 360
            minlatitude = -90
            maxlatitude = 90
        else:
            domain_points = self.comm.query.inner_domain_corners()
            minlongitude = domain_points["bottom_left"]["longitude"]
            maxlongitude = domain_points["upper_right"]["longitude"]
            minlatitude = domain_points["bottom_left"]["latitude"]
            maxlatitude = domain_points["upper_right"]["latitude"]


        inventory = Inventory()
        print("Querying station availability. This might take a while ...")
        for client_name in sorted(URL_MAPPINGS.keys()):
            client = Client(client_name)
            try:
                inv = client.get_stations(starttime=starttime, endtime=endtime, channel="*Z",
                                                minlongitude=minlongitude, maxlongitude=maxlongitude,
                                                minlatitude=minlatitude, maxlatitude=maxlatitude)
                print("\tSucessfull query at %s"%client_name)
            except Exception:
                continue
            if inv:
                inventory.extend(inv)
        return inventory


    def _get_stationxml_storage_fct(self, starttime, endtime):
        # Get the stationxml storage function required by the download helpers.
        time_of_interest = starttime + 0.5 * (endtime - starttime)
        root_path = self.comm.project.paths["station_xml"]

        def stationxml_storage(network, station, channels, startime, endtime):
            missing_channels = []
            available_channels = []
            for loc_code, cha_code in channels:
                if not self.comm.stations.has_channel(
                    "%s.%s.%s.%s" % (network, station, loc_code,
                                     cha_code), time_of_interest):
                    missing_channels.append((loc_code, cha_code))
                else:
                    available_channels.append((loc_code, cha_code))
            _i = 0
            while True:
                path = os.path.join(root_path, "%s.%s%s.xml" % (
                    network, station, _i if _i >= 1 else ""))
                if os.path.exists(path):
                    _i += 1
                    continue
                break

            return {
                "available_channels": available_channels,
                "missing_channels": missing_channels,
                "filename": path
            }

        return stationxml_storage

    def _get_spherical_section_domain(self, domain):
        from obspy.clients.fdsn.mass_downloader import Domain

        # Make copies to assure the closure binds correctly.
        d = copy.deepcopy(domain)

        class SphericalSectionDomain(Domain):
            def get_query_parameters(self):
                center = d.center
                return {
                    "latitude": center.latitude,
                    "longitude": center.longitude,
                    "minradius": 0.0,
                    "maxradius": d.max_extent / 2.0
                }

            def is_in_domain(self, latitude, longitude):
                return d.point_in_domain(latitude=latitude,
                                         longitude=longitude)

        return SphericalSectionDomain()

    def _get_maximum_bounds(self, min_lat, max_lat, min_lng, max_lng,
                            rotation_axis, rotation_angle_in_degree):
        """
        Small helper function to get the domain bounds of a rotated spherical
        section.

        :param min_lat: Minimum Latitude of the unrotated section.
        :param max_lat: Maximum Latitude of the unrotated section.
        :param min_lng: Minimum Longitude of the unrotated section.
        :param max_lng: Maximum Longitude of the unrotated section.
        :param rotation_axis: Rotation axis as a list in the form of [x, y, z]
        :param rotation_angle_in_degree: Rotation angle in degree.
        """
        number_of_points_per_side = 50
        north_border = np.empty((number_of_points_per_side, 2))
        south_border = np.empty((number_of_points_per_side, 2))
        east_border = np.empty((number_of_points_per_side, 2))
        west_border = np.empty((number_of_points_per_side, 2))

        north_border[:, 0] = np.linspace(min_lng, max_lng,
                                         number_of_points_per_side)
        north_border[:, 1] = min_lat

        south_border[:, 0] = np.linspace(max_lng, min_lng,
                                         number_of_points_per_side)
        south_border[:, 1] = max_lat

        east_border[:, 0] = max_lng
        east_border[:, 1] = np.linspace(min_lat, max_lat,
                                        number_of_points_per_side)

        west_border[:, 0] = min_lng
        west_border[:, 1] = np.linspace(max_lat, min_lat,
                                        number_of_points_per_side)

        # Rotate everything.
        for border in [north_border, south_border, east_border, west_border]:
            for _i in range(number_of_points_per_side):
                border[_i, 1], border[_i, 0] = rotations.rotate_lat_lon(
                    border[_i, 1], border[_i, 0], rotation_axis,
                    rotation_angle_in_degree)

        border = np.concatenate([north_border, south_border, east_border,
                                 west_border])

        min_lng, max_lng = border[:, 0].min(), border[:, 0].max()
        min_lat, max_lat = border[:, 1].min(), border[:, 1].max()

        return min_lat, max_lat, min_lng, max_lng
