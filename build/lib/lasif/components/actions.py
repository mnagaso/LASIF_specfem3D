#!/usr/bin/env python
# -*- coding: utf-8 -*-


import itertools
import numpy as np
import os
import warnings

from lasif import LASIFError, LASIFWarning, LASIFNotFoundError
from lasif import rotations
from .component import Component
from obspy.taup import TauPyModel
from obspy.geodetics import locations2degrees



class ActionsComponent(Component):
    """
    Component implementing actions on the data. Requires most other
    components to be available.

    :param communicator: The communicator instance.
    :param component_name: The name of this component for the communicator.
    """
    def preprocess_data(self, iteration_name, components = ['E','N','Z'], svd_selection = False, noise_threshold=None, event_names=None, recompute_files = False):
        """
        Preprocesses all data for a given iteration.

        This function works with and without MPI.

        :param event_names: event_ids is a list of events to process in this
            run. It will process all events if not given.
        """
        from mpi4py import MPI
        from lasif.tools.parallel_helpers import distribute_across_ranks

        iteration = self.comm.iterations.get(iteration_name)

        process_params = iteration.get_process_params()
        processing_tag = iteration.processing_tag

        # check the components
        ncomp = len(components)
        if ncomp>3:
            msg = ("There are more than 3 components given")
            raise LASIFError(msg)
        for comp in components:
            if comp not in ['E', 'N', 'Z', 'R', 'T']:
                msg = ("Component %s in not within the list: 'E', 'N', 'Z', 'R', 'T'"%comp)
                raise LASIFError(msg)

        # if we compute one of the two horizontal components, need to compute the other one
        if 'R' in components and not 'T' in components:
            components.append('T')
        if 'T' in components and not 'R' in components:
            components.append('R')
        if 'E' in components and not 'N' in components:
            components.append('N')
        if 'N' in components and not 'E' in components:
            components.append('E')

        comp_to_process = []
        if 'R' in components or 'T' in components:
            comp_to_process.append('E')
            comp_to_process.append('N')
        if 'E' in components:
            comp_to_process.append('E')
        if 'N' in components:
            comp_to_process.append('N')
        if 'Z' in components:
            comp_to_process.append('Z')

        earth_model = TauPyModel("ak135")
        
        

        def processing_data_generator():
            """
            Generate a dictionary with information for processing for each
            waveform.
            """
            def _check_if_output_file_exists(output_filename, channel, output_folder, components):
                if os.path.exists(output_filename):
                    if 'Z' not in channel["component"]:
                        if 'R' in components and 'T' in components:
                            output_filename_base = os.path.basename(output_filename).split('__')
                            R_output_filename = os.path.join(output_folder,
                                                               output_filename_base[0][:-1]
                                                               +'R__'+output_filename_base[1]
                                                               +'__'+output_filename_base[2])
                            T_output_filename = os.path.join(output_folder,
                                                               output_filename_base[0][:-1]
                                                               +'T__'+output_filename_base[1]
                                                               +'__'+output_filename_base[2])
                            if os.path.exists(R_output_filename) and os.path.exists(T_output_filename):
                                is_output = True
                        elif 'R' in components and 'T' not in components:
                            output_filename_base = os.path.basename(output_filename).split('__')
                            R_output_filename = os.path.join(output_folder,
                                                               output_filename_base[0][:-1]
                                                               +'R__'+output_filename_base[1]
                                                               +'__'+output_filename_base[2])
                            if os.path.exists(R_output_filename):
                                is_output = True
                        elif 'R' not in components and 'T' in components:
                            output_filename_base = os.path.basename(output_filename).split('__')
                            T_output_filename = os.path.join(output_folder,
                                                               output_filename_base[0][:-1]
                                                               +'T__'+output_filename_base[1]
                                                               +'__'+output_filename_base[2])
                            if os.path.exists(T_output_filename):
                                is_output = True
                        elif 'R' not in components and 'T' not in components:
                            is_output = True
                    else:
                        is_output = True
                else:
                    is_output = False
                return is_output
            
            
            # ----- Entering the function -----
            # Loop over the chosen events.
            for event_name, event in iteration.events.items():
                # None means to process all events, otherwise it will be a list
                # of events.

                if not ((event_names is None) or (event_name in event_names)):
                    #print("!!!!%s not defined in the iteration file !!!!"%event_name)
                    continue

                output_folder = self.comm.waveforms.get_waveform_folder(
                    event_name=event_name, data_type="processed",
                    tag_or_iteration=processing_tag)
                if not os.path.exists(output_folder):
                    os.makedirs(output_folder)

                # Get the event.
                event = self.comm.events.get(event_name)

                try:
                    # Get the stations.
                    stations = self.comm.query\
                        .get_all_stations_for_event(event_name)
                    # Get the raw waveform data.
                    waveforms = \
                        self.comm.waveforms.get_metadata_raw(event_name)
                except LASIFNotFoundError:
                    warnings.warn(
                        "No data found for event '%s'. Did you delete data "
                        "after the iteration has been created?" % event_name)
                    continue

                # Group by station name.
                def func(x):
                    return ".".join(x["channel_id"].split(".")[:2])

                waveforms.sort(key=func)
                for station_name, channels in  \
                        itertools.groupby(waveforms, func):
                    channels = list(channels)
                    # Filter waveforms with no available station files
                    # or coordinates.

                    if station_name not in stations:
                        continue

                    # Group by location.
                    def get_loc_id(x):
                        return x["channel_id"].split(".")[2]

                    channels.sort(key=get_loc_id)
                    locations = []
                    for loc_id, chans in itertools.groupby(channels,
                                                           get_loc_id):
                        locations.append((loc_id, list(chans)))
                    locations.sort(key=lambda x: x[0])

                    if len(locations) > 1:
                        msg = ("More than one location found for event "
                               "'%s' at station '%s'. The alphabetically "
                               "first one will be chosen." %
                               (event_name, station_name))
                        warnings.warn(msg, LASIFWarning)
                    location = locations[0][1]
                    

                    # compute the P-wave arrival time to be used for SNR calculation
                    channel = location[0].copy()
                    channel.update(stations[station_name])
                    dist_in_deg = locations2degrees(channel["latitude"], channel["longitude"], 
                                                    event["latitude"], event["longitude"])
                    tts = earth_model.get_travel_times(source_depth_in_km=event["depth_in_km"],
                                                       distance_in_degree=dist_in_deg,
                                                       phase_list=['P'])
                    if len(tts)==0:
                        print(("No P wave for station %s"%station_name))
                        continue
                    else:
                        # check the purist name
                        if len(tts)>1:
                            first_tt_arrival = tts[[i for i,j in enumerate(tts) if j.purist_name=='P'][0]].time
                        else:
                            first_tt_arrival  = tts[0].time

                    if channel["longitude"] is None or channel["longitude"] is None:
                        try:
                            sta_coordinates = self.comm.inventory_db.get_coordinates(channel["channel_id"])
                            channel["longitude"] = sta_coordinates["longitude"]
                            channel["latitude"] = sta_coordinates["latitude"]
                            channel["elevation_in_m"] = sta_coordinates["elevation_in_m"]
                            channel["local_depth_in_m"] = sta_coordinates["local_depth_in_m"]
                        except Exception:
                            continue

                    # station dictionary, will include all 3 components metadata info
                    channel_name = channel["channel_id"].split('.')
                    channel_name = channel_name[0]+'.'+channel_name[1]+'.'+channel_name[2]
                    station_dict = {"process_params": process_params,
                                    "event_information": event,
                                    "event_name": event_name,
                                    "station": channel_name,
                                    "station_coordinates": {
                                        "latitude": channel["latitude"],
                                        "longitude": channel["longitude"],
                                        "elevation_in_m": channel["elevation_in_m"],
                                        "local_depth_in_m": channel[
                                            "local_depth_in_m"],},
                                    "first_P_arrival": first_tt_arrival,
                                    "waveforms" : {}
                                    }

                    # Loop over each found channel.
                    wav_dict = {}
                    for channel in location:
                        channel.update(stations[station_name])
                        channel["component"] = channel["channel_id"].split('.')[-1][-1]
                        if channel["component"] not in comp_to_process:
                            continue

                        input_filename = channel["filename"]
                        output_filename = os.path.join(
                            output_folder,
                            os.path.basename(input_filename))


                        # Skip already processed files.
                        if recompute_files == "False":
                            is_output = _check_if_output_file_exists(output_filename, channel, output_folder, components)
                            if is_output is True:
                                continue
                            

                        # Xml Station file
                        try:
                            station_filename = self.comm.stations.get_channel_filename(channel["channel_id"],
                                                                                   channel["starttime"])
                        except Exception as e:
                            msg = (e.__repr__())
                            warnings.warn(msg, LASIFWarning)
                            continue
                            
                        '''
                        # for RESP files
                        station_filename = \
                            self.comm.stations.get_station_filename(channel["network"], 
                                                                    channel["station"], channel["location"],
                                                                    channel["channel"], 'RESP')
                        if station_filename.endswith('.1'):
                            station_filename = station_filename.strip('.1')
                        '''

                        ret_dict = {
                            "input_filename": input_filename,
                            "output_filename": output_filename,
                            "station_filename": station_filename,
                            "channel": channel["channel"]
                        }
                        wav_dict[channel["channel_id"]] = ret_dict

                    station_dict.update({"waveforms": wav_dict})
                    yield station_dict
                
        
        
        # Only rank 0 needs to know what has to be processsed.
        if MPI.COMM_WORLD.rank == 0:
            if noise_threshold == None:
                to_be_processed = [{"components": components, "processing_info": _i, "iteration": iteration}
                                   for _i in processing_data_generator() if _i["waveforms"]]
            else:
                to_be_processed = [{"components": components, "noise_threshold": noise_threshold, "processing_info": _i, "iteration": iteration}
                                   for _i in processing_data_generator() if _i["waveforms"]]
        else:
            to_be_processed = None
        if not to_be_processed:
            print("No data files to be processed")


        logfile = self.comm.project.get_log_file(
            "DATA_PREPROCESSING", "processing_iteration_%s" % (str(
                iteration.name)))
        
        # write header to log file
        with open(logfile, "at") as fh:
            fh.write('--------------------------------------------------------------------\n')
            fh.write("Processing info for iteration %s\n"%iteration_name)
            if event_names is None:
                fh.write("\tfor all events in the database\n") 
            else:
                fh.write("\tfor %d events in the database\n"%len(event_names)) 
            fh.write("\tfor components:\n")
            for comp in components:
                fh.write("\t\t\t%s\n"%comp)
            if noise_threshold is None:
                fh.write("\twith noise threshold by default (see preprocessing_function)\n")
            else:
                fh.write("\twith noise threshold %0.2f\n"%noise_threshold)
            if svd_selection == "True":
                fh.write("\tApply SVD based selection (see data_svd_selection function)\n")
            fh.write('--------------------------------------------------------------------\n')
        fh.close()
    

        # Load project specific data preprocessing function.
        preprocessing_function = self.comm.project.get_project_function(
            "preprocessing_function")
        
        # parallel run
        distribute_across_ranks(
            function=preprocessing_function, items=to_be_processed,
            get_name=lambda x: "%s -- %s"\
                %(x["processing_info"]["event_name"], x["processing_info"]["station"]),
            logfile=logfile)



        ###################################################
        # svd to be computed only for teleseismic events :
        ##################################################
        if svd_selection== "True":
            # Load project specific data selection function.
            data_svd_selection = self.comm.project.get_project_function(
                "data_svd_selection") 

            # Loop over the chosen events.
            for event_name, event in iteration.events.items():
                if not ((event_names is None) or (event_name in event_names)):
                    continue

                one_event_to_be_processed = [proc["processing_info"] for proc in to_be_processed
                                             if event_name in proc["processing_info"]["event_name"]]                

                # This is for reformatting the metadat info dictionnary to fit with the data_svd_selection function
                # This is repeatitive tasks - not clean, could be improved
                to_be_processed_for_svd = []
                for i,item in enumerate(one_event_to_be_processed):
                    for channel_id in item["waveforms"]:
                        output_filename = item["waveforms"][channel_id]["output_filename"]
                        channel = item["waveforms"][channel_id]["channel"]
                        if 'R' in components and 'E' in channel:
                            channel = channel.replace('E','R')
                            output_filename_base = os.path.basename(output_filename).split('__')
                            output_filename = os.path.join(os.path.dirname(output_filename),
                                                           output_filename_base[0][:-1]
                                                           +'R__'+output_filename_base[1]
                                                           +'__'+output_filename_base[2])
                        elif 'T' in components and 'N' in channel:
                            channel = channel.replace('N','T')
                            output_filename_base = os.path.basename(output_filename).split('__')
                            output_filename = os.path.join(os.path.dirname(output_filename),
                                                           output_filename_base[0][:-1]
                                                           +'T__'+output_filename_base[1]
                                                           +'__'+output_filename_base[2])

                        to_be_processed_for_svd.append({"process_params": item["process_params"],
                                                        "event_information": item["event_information"],
                                                        "event_name": item["event_name"],
                                                        "station": item["station"],
                                                        "station_coordinates": item["station_coordinates"],
                                                        "first_P_arrival": item["first_P_arrival"],
                                                        "station_filename": item["waveforms"][channel_id]["station_filename"],
                                                        "channel": channel,
                                                        "output_filename": output_filename})


                print(("\nProcessing SVD selection for %s"%event_name))
                data_svd_selection(to_be_processed_for_svd, components)





    def stf_estimate(self, iteration_name, components = ['E','N','Z'], event_names=None):
        """
        Estimate the source wavelet by deconvolving the synthetics from data
        following Pratt, R. G. (1999), 
        Seismic waveform inversion in the frequency domain, part 1: Theory and verification in a physical scale model

        This function works with and without MPI.

        :param event_names: event_ids is a list of events to process in this
            run. It will process all events if not given.
        """
        from mpi4py import MPI
        from lasif.tools.parallel_helpers import distribute_across_ranks
        import instaseis

        iteration = self.comm.iterations.get(iteration_name)


        process_params = iteration.get_process_params()
        processing_tag = iteration.processing_tag

        # check the components
        ncomp = len(components)
        if ncomp>3:
            msg = ("There are more than 3 components given")
            raise LASIFError(msg)
        for comp in components:
            if comp not in ['E', 'N', 'Z', 'R', 'T']:
                msg = ("Component %s in not within the list: 'E', 'N', 'Z', 'R', 'T'"%comp)
                raise LASIFError(msg)

        # if we compute one of the two horizontal components, need to compute the other one
        if 'R' in components and not 'T' in components:
            components.append('T')
        if 'T' in components and not 'R' in components:
            components.append('R')
        if 'E' in components and not 'N' in components:
            components.append('N')
        if 'N' in components and not 'E' in components:
            components.append('E')

        comp_to_process = components

        earth_model = TauPyModel("ak135")
        try:
            db = instaseis.open_db("syngine://ak135f_2s")
        except:
            raise LASIFError("Having troubles loading the Earth model database from syngine, check your Internet connection")

        def processing_instaseis_synthetics_generator():
            """
            Generate a dictionary with information for processing for each
            synthetic waveform.
            """

            # Loop over the chosen events.
            for event_name, event in iteration.events.items():
                # None means to process all events, otherwise it will be a list
                # of events.

                if not ((event_names is None) or (event_name in event_names)):
                    #print("!!!!%s not defined in the iteration file !!!!"%event_name)
                    continue

                output_folder = self.comm.waveforms.get_waveform_folder(
                    event_name=event_name, data_type="synthetic",
                    tag_or_iteration="ITERATION_%s"%iteration_name)
                if not os.path.exists(output_folder):
                    os.makedirs(output_folder)

                # Get the event.
                event = self.comm.events.get(event_name)

                # get the source
                source=instaseis.Source.parse(event["filename"])
                event["source"] = source

                try:
                    # Get the stations.
                    stations = self.comm.query\
                        .get_all_stations_for_event(event_name)
                    # Get the processed waveform data.
                    waveforms = \
                        self.comm.waveforms.get_metadata_processed(event_name, processing_tag)
                except LASIFNotFoundError:
                    warnings.warn(
                        "No data found for event '%s'. Did you delete data "
                        "after the iteration has been created?" % event_name)
                    continue

                # Group by station name.
                def func(x):
                    return ".".join(x["channel_id"].split(".")[:2])

                waveforms.sort(key=func)
                for station_name, channels in  \
                        itertools.groupby(waveforms, func):
                    channels = list(channels)
                    # Filter waveforms with no available station files
                    # or coordinates.

                    if station_name not in stations:
                        continue

                    # Group by location.
                    def get_loc_id(x):
                        return x["channel_id"].split(".")[2]

                    channels.sort(key=get_loc_id)
                    locations = []
                    for loc_id, chans in itertools.groupby(channels,
                                                           get_loc_id):
                        locations.append((loc_id, list(chans)))
                    locations.sort(key=lambda x: x[0])

                    if len(locations) > 1:
                        msg = ("More than one location found for event "
                               "'%s' at station '%s'. The alphabetically "
                               "first one will be chosen." %
                               (event_name, station_name))
                        warnings.warn(msg, LASIFWarning)
                    location = locations[0][1]

                    # Loop over each found channel.
                    for channel in location:
                        channel.update(stations[station_name])
                        channel["component"]= channel["channel_id"].split('.')[-1][-1]
                        if channel["longitude"] is None or channel["longitude"] is None:
                            try:
                                sta_coordinates = self.comm.inventory_db.get_coordinates(channel["channel_id"])
                                channel["longitude"] = sta_coordinates["longitude"]
                                channel["latitude"] = sta_coordinates["latitude"]
                                channel["elevation_in_m"] = sta_coordinates["elevation_in_m"]
                                channel["local_depth_in_m"] = sta_coordinates["local_depth_in_m"]
                            except Exception:
                                continue

                        input_filename = channel["filename"]
                        output_filename = os.path.join(
                            output_folder,
                            os.path.basename(input_filename))
                        # Skip already processed files.
                        #if os.path.exists(output_filename):
                        #    continue
                        
                        # get station_file to parse to instaseis
                        station_filename = \
                            self.comm.stations.get_channel_filename(channel["channel_id"][:-1]+'Z',
                                                                    channel["starttime"])
                        receiver = instaseis.Receiver.parse(station_filename)[0]
                        # if RESP file, fill the station coordinates
                        if '/RESP/' in station_filename:
                            receiver.latitude = channel["latitude"]
                            receiver.longitude = channel["longitude"]
                        

                        '''
                        # force to StationXML file
                        station_filename = \
                            self.comm.stations.get_station_filename(channel["network"], 
                                                                    channel["station"], channel["location"],
                                                                    channel["channel"], 'StationXML')
                        receiver = instaseis.Receiver.parse(station_filename)[0]
                        print(station_filename)
                        print(receiver)
                        '''


                        # compute the P-wave arrival time to be used for SNR calculation
                        dist_in_deg = locations2degrees(channel["latitude"], channel["longitude"], 
                                                        event["latitude"], event["longitude"])
                        tts = earth_model.get_travel_times(source_depth_in_km=event["depth_in_km"],
                                                           distance_in_degree=dist_in_deg,
                                                           phase_list=['P'])

                        if len(tts)==0:
                            print(("No P wave for epicentral distance %f"%dist_in_deg))
                            continue
                        else:
                            # check the purist name
                            if len(tts)>1:
                                first_tt_arrival = tts[[i for i,j in enumerate(tts) if j.purist_name=='P'][0]].time
                            else:
                                first_tt_arrival  = tts[0].time


                        ret_dict = {
                            "process_params": process_params,
                            "input_filename": input_filename,
                            "output_filename": output_filename,
                            "channel": channel["channel"],
                            "channel_id": channel["channel_id"],
                            "station": channel["station"],
                            "component": channel["component"],
                            "station_coordinates": {
                                "latitude": channel["latitude"],
                                "longitude": channel["longitude"],
                                "elevation_in_m": channel["elevation_in_m"],
                                "local_depth_in_m": channel[
                                    "local_depth_in_m"],
                            },
                            "station_filename": station_filename,
                            "receiver": receiver,
                            "event_information": event,
                            "event_name": event_name,
                            "first_P_arrival":first_tt_arrival
                        }

                        yield ret_dict

        # Only rank 0 needs to know what has to be processsed.
        if MPI.COMM_WORLD.rank == 0:
            to_be_processed = [{"db": db, "processing_info": _i, "iteration": iteration}
                               for _i in processing_instaseis_synthetics_generator()
                               if _i["component"] in comp_to_process]
            # for the synthetics: compute only non-processed synthetic files
            synthetics_to_process = [{"db": db, "processing_info": _i["processing_info"], "iteration": iteration}
                                     for _i in to_be_processed
                                     if not os.path.exists(_i["processing_info"]["output_filename"])]
        else:
            to_be_processed = None
            synthetics_to_process = None
        if not synthetics_to_process:
            print("No synthetic files to be processed")
        else:    
        

            # Load project specific synthetics computing function.
            instaseis_synthetics_function = self.comm.project.get_project_function(
                "instaseis_synthetics_function")
    
    
            logfile = self.comm.project.get_log_file(
                "SYNTHETICS", "instaseis_synthetics_iteration_%s" % (str(
                    iteration.name)))
            
            # write header to log file
            with open(logfile, "at") as fh:
                fh.write('--------------------------------------------------------------------\n')
                fh.write("Synthetic info for iteration %s\n"%iteration_name)
                if event_names is None:
                    fh.write("\tfor all events in the database\n") 
                else:
                    fh.write("\tfor %d events in the database\n"%len(event_names)) 
                fh.write("\tfor components:\n")
                for comp in components:
                    fh.write("\t\t\t%s\n"%comp)
                fh.write('--------------------------------------------------------------------\n')
            fh.close()
    
    
            
            distribute_across_ranks(
                function=instaseis_synthetics_function, items=synthetics_to_process,
                get_name=lambda x: "%s -- %s"\
                %(x["processing_info"]["event_name"], x["processing_info"]["channel_id"]),
                logfile=logfile)

        
        # Load project specific stf_deconvolution function.
        stf_deconvolution = self.comm.project.get_project_function(
            "stf_deconvolution") 

        # Loop over the chosen events.
        for event_name, event in iteration.events.items():
            if not ((event_names is None) or (event_name in event_names)):
                continue

            one_event_to_be_processed = [proc for proc in to_be_processed
                                         if event_name in proc["processing_info"]["event_name"]]
            if one_event_to_be_processed:
                output_folder = self.comm.waveforms.get_waveform_folder(
                    event_name=event_name, data_type="stf",
                    tag_or_iteration='ITERATION_%s'%iteration_name)
                if not os.path.exists(output_folder):
                    os.makedirs(output_folder)
    
                print(("\nEstimating the stf for %s"%event_name))
                stf_deconvolution(one_event_to_be_processed, output_folder, components)
            else:
                print("\nNo data for this event, will skip the stf estimation")
                continue




    def select_windows(self, event, iteration):
        """
        Automatically select the windows for the given event and iteration.

        Will only attempt to select windows for stations that have no
        windows. Each station that has a window is assumed to have already
        been picked in some fashion.

        Function can be called with and without MPI.

        :param event: The event.
        :param iteration: The iteration.
        """
        from lasif.utils import channel2station
        from mpi4py import MPI

        event = self.comm.events.get(event)
        iteration = self.comm.iterations.get(iteration)

        def split(container, count):
            """
            Simple and elegant function splitting a container into count
            equal chunks.

            Order is not preserved but for the use case at hand this is
            potentially an advantage as data sitting in the same folder thus
            have a higher at being processed at the same time thus the disc
            head does not have to jump around so much. Of course very
            architecture dependent.
            """
            return [container[_i::count] for _i in range(count)]

        # Only rank 0 needs to know what has to be processsed.
        if MPI.COMM_WORLD.rank == 0:
            # All stations for the given iteration and event.
            stations = \
                set(iteration.events[event["event_name"]]["stations"].keys())

            # Get all stations that currently do not have windows.
            windows = self.comm.windows.get(event, iteration).list()
            stations_without_windows = \
                stations - set(map(channel2station, windows))
            total_size = len(stations_without_windows)
            stations_without_windows = split(list(stations_without_windows),
                                             MPI.COMM_WORLD.size)

            # Initialize station cache on rank 0.
            self.comm.stations.file_count
            # Also initialize the processed and synthetic data caches. They
            # have to exist before the other ranks can access them.
            try:
                self.comm.waveforms.get_waveform_cache(
                    event["event_name"], "processed", iteration.processing_tag)
            except LASIFNotFoundError:
                pass
            try:
                self.comm.waveforms.get_waveform_cache(
                    event["event_name"], "synthetic", iteration)
            except LASIFNotFoundError:
                pass
        else:
            stations_without_windows = None

        # Distribute on a per-station basis.
        stations_without_windows = MPI.COMM_WORLD.scatter(
            stations_without_windows, root=0)

        for _i, station in enumerate(stations_without_windows):
            try:
                self.select_windows_for_station(event, iteration, station)
            except LASIFNotFoundError as e:
                warnings.warn(str(e), LASIFWarning)
            except Exception as e:
                warnings.warn(
                    "Exception occured for iteration %s, event %s, and "
                    "station %s: %s" % (iteration.name, event["event_name"],
                                        station, str(e)), LASIFWarning)
            if MPI.COMM_WORLD.rank == 0:
                print(("Window picking process: Picked windows for approx. %i "
                      "of %i stations." % (
                          min(_i * MPI.COMM_WORLD.size, total_size),
                          total_size)))

        # Barrier at the end useful for running this in a loop.
        MPI.COMM_WORLD.barrier()

    def select_windows_for_station(self, event, iteration, station, **kwargs):
        """
        Selects windows for the given event, iteration, and station. Will
        delete any previously existing windows for that station if any.

        :param event: The event.
        :param iteration: The iteration.
        :param station: The station id in the form NET.STA.
        """
        from lasif.utils import select_component_from_stream

        # Load project specific window selection function.
        select_windows = self.comm.project.get_project_function(
            "window_picking_function")

        event = self.comm.events.get(event)
        iteration = self.comm.iterations.get(iteration)
        data = self.comm.query.get_matching_waveforms(event, iteration,
                                                      station)

        process_params = iteration.get_process_params()
        minimum_period = 1.0 / process_params["lowpass"]
        maximum_period = 1.0 / process_params["highpass"]

        window_group_manager = self.comm.windows.get(event, iteration)
        # Delete the windows for this stations.
        window_group_manager.delete_windows_for_station(station)

        found_something = False
        for component in ["E", "N", "Z"]:
            try:
                data_tr = select_component_from_stream(data.data, component)
                synth_tr = select_component_from_stream(data.synthetics,
                                                        component)
            except LASIFNotFoundError:
                continue
            found_something = True

            windows = select_windows(data_tr, synth_tr, event["latitude"],
                                     event["longitude"], event["depth_in_km"],
                                     data.coordinates["latitude"],
                                     data.coordinates["longitude"],
                                     minimum_period=minimum_period,
                                     maximum_period=maximum_period,
                                     iteration=iteration, **kwargs)
            if not windows:
                continue

            window_group = window_group_manager.get(data_tr.id)
            for starttime, endtime in windows:
                window_group.add_window(starttime=starttime, endtime=endtime)
            window_group.write()

        if found_something is False:
            raise LASIFNotFoundError(
                "No matching data found for event '%s', iteration '%s', and "
                "station '%s'." % (event["event_name"], iteration.name,
                                   station))

    def generate_input_files(self, iteration_name, event_name,
                             simulation_type):
        """
        Generate the input files for one event.

        :param iteration_name: The name of the iteration.
        :param event_name: The name of the event for which to generate the
            input files.
        :param simulate_type: The type of simulation to perform. Possible
            values are: 'normal simulate', 'adjoint forward', 'adjoint
            reverse'
        """
        from wfs_input_generator import InputFileGenerator

        # =====================================================================
        # read iteration xml file, get event and list of stations
        # =====================================================================

        iteration = self.comm.iterations.get(iteration_name)

        # Check that the event is part of the iterations.
        if event_name not in iteration.events:
            msg = ("Event '%s' not part of iteration '%s'.\nEvents available "
                   "in iteration:\n\t%s" %
                   (event_name, iteration_name, "\n\t".join(
                       sorted(iteration.events.keys()))))
            raise ValueError(msg)

        event = self.comm.events.get(event_name)
        stations_for_event = list(iteration.events[event_name]["stations"].keys())

        # Get all stations and create a dictionary for the input file
        # generator.
        stations = self.comm.query.get_all_stations_for_event(event_name)
        stations = [{"id": key, "latitude": value["latitude"],
                     "longitude": value["longitude"],
                     "elevation_in_m": value["elevation_in_m"],
                     "local_depth_in_m": value["local_depth_in_m"]}
                    for key, value in stations.items()
                    if key in stations_for_event]

        # =====================================================================
        # set solver options
        # =====================================================================

        solver = iteration.solver_settings

        # Currently only SES3D 4.1 is supported
        solver_format = solver["solver"].lower()
        if solver_format not in ["ses3d 4.1", "ses3d 2.0",
                                 "specfem3d cartesian", "specfem3d globe cem"]:
            msg = ("Currently only SES3D 4.1, SES3D 2.0, SPECFEM3D "
                   "CARTESIAN, and SPECFEM3D GLOBE CEM are supported.")
            raise ValueError(msg)
        solver_format = solver_format.replace(' ', '_')
        solver_format = solver_format.replace('.', '_')

        solver = solver["solver_settings"]

        # =====================================================================
        # create the input file generator, add event and stations,
        # populate the configuration items
        # =====================================================================

        # Add the event and the stations to the input file generator.
        gen = InputFileGenerator()
        gen.add_events(event["filename"])
        gen.add_stations(stations)

        if solver_format in ["ses3d_4_1", "ses3d_2_0"]:
            # event tag
            gen.config.event_tag = event_name

            # Time configuration.
            npts = solver["simulation_parameters"]["number_of_time_steps"]
            delta = solver["simulation_parameters"]["time_increment"]
            gen.config.number_of_time_steps = npts
            gen.config.time_increment_in_s = delta

            # SES3D specific configuration
            gen.config.output_folder = solver["output_directory"].replace(
                "{{EVENT_NAME}}", event_name.replace(" ", "_"))
            gen.config.simulation_type = simulation_type

            gen.config.adjoint_forward_wavefield_output_folder = \
                solver["adjoint_output_parameters"][
                    "forward_field_output_directory"].replace(
                    "{{EVENT_NAME}}", event_name.replace(" ", "_"))
            gen.config.adjoint_forward_sampling_rate = \
                solver["adjoint_output_parameters"][
                    "sampling_rate_of_forward_field"]

            # Visco-elastic dissipation
            diss = solver["simulation_parameters"]["is_dissipative"]
            gen.config.is_dissipative = diss

            # Only SES3D 4.1 has the relaxation parameters.
            if solver_format == "ses3d_4_1":
                gen.config.Q_model_relaxation_times = \
                    solver["relaxation_parameter_list"]["tau"]
                gen.config.Q_model_weights_of_relaxation_mechanisms = \
                    solver["relaxation_parameter_list"]["w"]

            # Discretization
            disc = solver["computational_setup"]
            gen.config.nx_global = disc["nx_global"]
            gen.config.ny_global = disc["ny_global"]
            gen.config.nz_global = disc["nz_global"]
            gen.config.px = disc["px_processors_in_theta_direction"]
            gen.config.py = disc["py_processors_in_phi_direction"]
            gen.config.pz = disc["pz_processors_in_r_direction"]
            gen.config.lagrange_polynomial_degree = \
                disc["lagrange_polynomial_degree"]

            # Configure the mesh.
            domain = self.comm.project.domain
            gen.config.mesh_min_latitude = domain.min_latitude
            gen.config.mesh_max_latitude = domain.max_latitude
            gen.config.mesh_min_longitude = domain.min_longitude
            gen.config.mesh_max_longitude = domain.max_longitude
            gen.config.mesh_min_depth_in_km = domain.min_depth_in_km
            gen.config.mesh_max_depth_in_km = domain.max_depth_in_km

            # Set the rotation parameters.
            gen.config.rotation_angle_in_degree = \
                domain.rotation_angle_in_degree
            gen.config.rotation_axis = domain.rotation_axis

            # Make source time function
            gen.config.source_time_function = \
                iteration.get_source_time_function()["data"]
        elif solver_format == "specfem3d_cartesian":
            gen.config.NSTEP = \
                solver["simulation_parameters"]["number_of_time_steps"]
            gen.config.DT = \
                solver["simulation_parameters"]["time_increment"]
            gen.config.NPROC = \
                solver["computational_setup"]["number_of_processors"]
            if simulation_type == "normal simulation":
                msg = ("'normal_simulate' not supported for SPECFEM3D "
                       "Cartesian. Please choose either 'adjoint_forward' or "
                       "'adjoint_reverse'.")
                raise NotImplementedError(msg)
            elif simulation_type == "adjoint forward":
                gen.config.SIMULATION_TYPE = 1
            elif simulation_type == "adjoint reverse":
                gen.config.SIMULATION_TYPE = 2
            else:
                raise NotImplementedError
            solver_format = solver_format.upper()

        elif solver_format == "specfem3d_globe_cem":
            cs = solver["computational_setup"]
            gen.config.NPROC_XI = cs["number_of_processors_xi"]
            gen.config.NPROC_ETA = cs["number_of_processors_eta"]
            gen.config.NCHUNKS = cs["number_of_chunks"]
            gen.config.NEX_XI = cs["elements_per_chunk_xi"]
            gen.config.NEX_ETA = cs["elements_per_chunk_eta"]
            gen.config.OCEANS = cs["simulate_oceans"]
            gen.config.ELLIPTICITY = cs["simulate_ellipticity"]
            gen.config.TOPOGRAPHY = cs["simulate_topography"]
            gen.config.GRAVITY = cs["simulate_gravity"]
            gen.config.ROTATION = cs["simulate_rotation"]
            gen.config.ATTENUATION = cs["simulate_attenuation"]
            gen.config.ABSORBING_CONDITIONS = True
            if cs["fast_undo_attenuation"]:
                gen.config.PARTIAL_PHYS_DISPERSION_ONLY = True
                gen.config.UNDO_ATTENUATION = False
            else:
                gen.config.PARTIAL_PHYS_DISPERSION_ONLY = False
                gen.config.UNDO_ATTENUATION = True
            gen.config.GPU_MODE = cs["use_gpu"]
            gen.config.SOURCE_TIME_FUNCTION = \
                iteration.get_source_time_function()["data"]

            if simulation_type == "normal simulation":
                gen.config.SIMULATION_TYPE = 1
                gen.config.SAVE_FORWARD = False
            elif simulation_type == "adjoint forward":
                gen.config.SIMULATION_TYPE = 1
                gen.config.SAVE_FORWARD = True
            elif simulation_type == "adjoint reverse":
                gen.config.SIMULATION_TYPE = 2
                gen.config.SAVE_FORWARD = True
            else:
                raise NotImplementedError

            # Use the current domain setting to derive the bounds in the way
            # SPECFEM specifies them.
            domain = self.comm.project.domain

            lat_range = domain.max_latitude - \
                domain.min_latitude
            lng_range = domain.max_longitude - \
                domain.min_longitude

            c_lat = \
                domain.min_latitude + lat_range / 2.0
            c_lng = \
                domain.min_longitude + lng_range / 2.0

            # Rotate the point.
            c_lat_1, c_lng_1 = rotations.rotate_lat_lon(
                c_lat, c_lng, domain.rotation_axis,
                domain.rotation_angle_in_degree)

            # SES3D rotation.
            A = rotations._get_rotation_matrix(
                domain.rotation_axis, domain.rotation_angle_in_degree)

            latitude_rotation = -(c_lat_1 - c_lat)
            longitude_rotation = c_lng_1 - c_lng

            # Rotate the latitude. The rotation axis is latitude 0 and
            # the center longitude + 90 degree
            B = rotations._get_rotation_matrix(
                rotations.lat_lon_radius_to_xyz(0.0, c_lng + 90, 1.0),
                latitude_rotation)
            # Rotate around the North pole.
            C = rotations._get_rotation_matrix(
                [0.0, 0.0, 1.0], longitude_rotation)

            D = A * np.linalg.inv(C * B)

            axis, angle = rotations._get_axis_and_angle_from_rotation_matrix(D)
            rotated_axis = rotations.xyz_to_lat_lon_radius(*axis)

            # Consistency check
            if abs(rotated_axis[0] - c_lat_1) >= 0.01 or \
                    abs(rotated_axis[1] - c_lng_1) >= 0.01:
                axis *= -1.0
                angle *= -1.0
                rotated_axis = rotations.xyz_to_lat_lon_radius(*axis)

            if abs(rotated_axis[0] - c_lat_1) >= 0.01 or \
                    abs(rotated_axis[1] - c_lng_1) >= 0.01:
                msg = "Failed to describe the domain in terms that SPECFEM " \
                      "understands. The domain definition in the output " \
                      "files will NOT BE CORRECT!"
                warnings.warn(msg, LASIFWarning)

            gen.config.ANGULAR_WIDTH_XI_IN_DEGREES = lng_range
            gen.config.ANGULAR_WIDTH_ETA_IN_DEGREES = lat_range
            gen.config.CENTER_LATITUDE_IN_DEGREES = c_lat_1
            gen.config.CENTER_LONGITUDE_IN_DEGREES = c_lng_1
            gen.config.GAMMA_ROTATION_AZIMUTH = angle

            gen.config.MODEL = cs["model"]

            pp = iteration.get_process_params()
            gen.config.RECORD_LENGTH_IN_MINUTES = \
                (pp["npts"] * pp["dt"]) / 60.0
            solver_format = solver_format.upper()

        else:
            msg = "Unknown solver '%s'." % solver_format
            raise NotImplementedError(msg)

        # =================================================================
        # output
        # =================================================================
        output_dir = self.comm.project.get_output_folder(
            type="input_files",
            tag="ITERATION_%s__%s__EVENT_%s" % (
                iteration_name, simulation_type.replace(" ", "_"),
                event_name))

        gen.write(format=solver_format, output_dir=output_dir)
        print("Written files to '%s'." % output_dir)

    def calculate_all_adjoint_sources(self, iteration_name, event_name):
        """
        Function to calculate all adjoint sources for a certain iteration
        and event.
        """
        window_manager = self.comm.windows.get(event_name, iteration_name)
        event = self.comm.events.get(event_name)
        iteration = self.comm.iterations.get(iteration_name)
        iteration_event_def = iteration.events[event["event_name"]]
        iteration_stations = iteration_event_def["stations"]

        l = sorted(window_manager.list())
        for station, windows in itertools.groupby(
                l, key=lambda x: ".".join(x.split(".")[:2])):
            if station not in iteration_stations:
                continue
            try:
                for w in windows:
                    w = window_manager.get(w)
                    for window in w:
                        # Access the property will trigger an adjoint source
                        # calculation.
                        window.adjoint_source
            except LASIFError as e:
                print(("Could not calculate adjoint source for iteration %s "
                      "and station %s. Repick windows? Reason: %s" % (
                          iteration.name, station, str(e))))

    def finalize_adjoint_sources(self, iteration_name, event_name):
        """
        Finalizes the adjoint sources.
        """
        
        import numpy as np
        from lasif import rotations

        window_manager = self.comm.windows.get(event_name, iteration_name)
        event = self.comm.events.get(event_name)
        iteration = self.comm.iterations.get(iteration_name)
        iteration_event_def = iteration.events[event["event_name"]]
        iteration_stations = iteration_event_def["stations"]

        # For now assume that the adjoint sources have the same
        # sampling rate as the synthetics which in LASIF's workflow
        # actually has to be true.
        dt = iteration.get_process_params()["dt"]

        # Current domain and solver.
        domain = self.comm.project.domain
        solver = iteration.solver_settings["solver"].lower()

        adjoint_source_stations = set()

        if "ses3d" in solver:
            ses3d_all_coordinates = []

        event_weight = iteration_event_def["event_weight"]

        output_folder = self.comm.project.get_output_folder(
            type="adjoint_sources",
            tag="ITERATION_%s__%s" % (iteration_name, event_name))

        l = sorted(window_manager.list())
        for station, windows in itertools.groupby(
                l, key=lambda x: ".".join(x.split(".")[:2])):
            if station not in iteration_stations:
                continue
            print(".", end=' ')
            station_weight = iteration_stations[station]["station_weight"]
            channels = {}
            try:
                for w in windows:
                    w = window_manager.get(w)
                    channel_weight = 0
                    srcs = []
                    for window in w:
                        ad_src = window.adjoint_source
                        if not ad_src["adjoint_source"].ptp():
                            continue
                        srcs.append(ad_src["adjoint_source"] * window.weight)
                        channel_weight += window.weight
                    if not srcs:
                        continue
                    # Final adjoint source for that channel and apply all
                    # weights.
                    adjoint_source = np.sum(srcs, axis=0) / channel_weight * \
                        event_weight * station_weight
                    channels[w.channel_id[-1]] = adjoint_source
            except LASIFError as e:
                print(("Could not calculate adjoint source for iteration %s "
                      "and station %s. Repick windows? Reason: %s" % (
                          iteration.name, station, str(e))))
                continue
            if not channels:
                continue
            # Now all adjoint sources of a window should have the same length.
            length = set(len(v) for v in list(channels.values()))
            assert len(length) == 1
            length = length.pop()
            # All missing channels will be replaced with a zero array.
            for c in ["Z", "N", "E"]:
                if c in channels:
                    continue
                channels[c] = np.zeros(length)

            # Get the station coordinates
            coords = self.comm.query.get_coordinates_for_station(event_name,
                                                                 station)

            # Rotate. if needed
            rec_lat = coords["latitude"]
            rec_lng = coords["longitude"]

            # The adjoint sources depend on the solver.
            if "ses3d" in solver:
                # Rotate if needed.
                if domain.rotation_angle_in_degree:
                    # Rotate the adjoint source location.
                    r_rec_lat, r_rec_lng = rotations.rotate_lat_lon(
                        rec_lat, rec_lng, domain.rotation_axis,
                        -domain.rotation_angle_in_degree)
                    # Rotate the adjoint sources.
                    channels["N"], channels["E"], channels["Z"] = \
                        rotations.rotate_data(
                            channels["N"], channels["E"],
                            channels["Z"], rec_lat, rec_lng,
                            domain.rotation_axis,
                            -domain.rotation_angle_in_degree)
                else:
                    r_rec_lat = rec_lat
                    r_rec_lng = rec_lng
                r_rec_depth = 0.0
                r_rec_colat = rotations.lat2colat(r_rec_lat)

                # Now once again map from ZNE to the XYZ of SES3D.
                CHANNEL_MAPPING = {"X": "N", "Y": "E", "Z": "Z"}
                adjoint_source_stations.add(station)
                adjoint_src_filename = os.path.join(
                    output_folder, "ad_src_%i" % len(adjoint_source_stations))
                ses3d_all_coordinates.append(
                    (r_rec_colat, r_rec_lng, r_rec_depth))

                # Actually write the adjoint source file in SES3D specific
                # format.
                with open(adjoint_src_filename, "wb") as open_file:
                    open_file.write("-- adjoint source ------------------\n")
                    open_file.write(
                        "-- source coordinates (colat,lon,depth)\n")
                    open_file.write("%f %f %f\n" % (r_rec_colat, r_rec_lng,
                                                    r_rec_depth))
                    open_file.write("-- source time function (x, y, z) --\n")
                    # Revert the X component as it has to point south in SES3D.
                    for x, y, z in zip(-1.0 * channels[CHANNEL_MAPPING["X"]],
                                        channels[CHANNEL_MAPPING["Y"]],
                                        channels[CHANNEL_MAPPING["Z"]]):
                        open_file.write("%e %e %e\n" % (x, y, z))
                    open_file.write("\n")
            elif "specfem" in solver:
                s_set = iteration.solver_settings["solver_settings"]
                if "adjoint_source_time_shift" not in s_set:
                    warnings.warn("No <adjoint_source_time_shift> tag in the "
                                  "iteration XML file. No time shift for the "
                                  "adjoint sources will be applied.",
                                  LASIFWarning)
                    src_time_shift = 0
                else:
                    src_time_shift = float(s_set["adjoint_source_time_shift"])
                adjoint_source_stations.add(station)
                # Write all components. The adjoint sources right now are
                # not time shifted.
                for component in ["Z", "N", "E"]:
                    # XXX: M band code could be different.
                    adjoint_src_filename = os.path.join(
                        output_folder, "%s.MX%s.adj" % (station, component))
                    adj_src = channels[component]
                    l = len(adj_src)
                    to_write = np.empty((l, 2))
                    to_write[:, 0] = \
                        np.linspace(0, (l - 1) * dt, l) + src_time_shift

                    # SPECFEM expects non-time reversed adjoint sources and
                    # the sign is different for some reason.
                    to_write[:, 1] = -1.0 * adj_src[::-1]

                    np.savetxt(adjoint_src_filename, to_write)
            else:
                raise NotImplementedError(
                    "Adjoint source writing for solver '%s' not yet "
                    "implemented." % iteration.solver_settings["solver"])

        if not adjoint_source_stations:
            print("Could not create a single adjoint source.")
            return

        if "ses3d" in solver:
            with open(os.path.join(output_folder, "ad_srcfile"), "wb") as fh:
                fh.write("%i\n" % len(adjoint_source_stations))
                for line in ses3d_all_coordinates:
                    fh.write("%.6f %.6f %.6f\n" % (line[0], line[1], line[2]))
                fh.write("\n")
        elif "specfem" in solver:
            adjoint_source_stations = sorted(list(adjoint_source_stations))
            with open(os.path.join(output_folder, "STATIONS_ADJOINT"),
                      "wb") as fh:
                for station in adjoint_source_stations:
                    coords = self.comm.query.get_coordinates_for_station(
                        event_name, station)
                    fh.write("{sta} {net} {lat} {lng} {ele} {dep}\n".format(
                        sta=station.split(".")[1],
                        net=station.split(".")[0],
                        lat=coords["latitude"],
                        lng=coords["longitude"],
                        ele=coords["elevation_in_m"],
                        dep=coords["local_depth_in_m"]))

        print("Wrote adjoint sources for %i station(s) to %s." % (
            len(adjoint_source_stations), os.path.relpath(output_folder)))
