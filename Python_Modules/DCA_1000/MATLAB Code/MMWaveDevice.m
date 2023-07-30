classdef MMWaveDevice
    %MMWaveDevice Summary of this class goes here
    %   Detailed explanation goes here
    
    properties
        freq
        lambda
        aoa_angle %not using yet
        num_angle %not using yet
        num_byte_per_sample
        rx_chanl_enable
        num_rx_chnl
        win_hann
        adc_samp_rate
        adc_bits
        dbfs_coeff
        
        %key chirp/frame data
        chirp_slope
        bw
        chirp_ramp_time
        chirp_idle_time
        chirp_adc_start_time
        frame_periodicity
        num_frame
        num_sample_per_frame
        size_per_frame %bytes per frame
        num_sample_per_chirp
        num_chirp_per_frame
        
        %radar performance specs
        range_max
        range_res
        v_max
        v_res
        
        %deals with data storate
        is_iq_swap
        is_interleave
        
        
    end
    
    methods
        function obj = MMWaveDevice(adc_data_bin_file,mmwave_setup_json_file)
            %{
            MMWaveDevice reads the mmwave_setup json file containing
            useful information on the mmwave device configuration
                Inputs:
                    adc_data_bin_file: path to the the bin file of the raw ADC data generated from
                        the DCA1000 board
                    mwave_setup_json_file: path to the mmwave.json file generated in mmwave studio 
                Outputs:
            %}
            
            % read json config format
            sys_param_json = jsondecode(fileread(mmwave_setup_json_file));

            %set frequency, wavelength, and angle of arrival information
            obj.freq = sys_param_json.mmWaveDevices.rfConfig.rlProfiles.rlProfileCfg_t.startFreqConst_GHz * 1e9;
            obj.lambda = physconst('LightSpeed') / obj.freq;

            obj.aoa_angle = 0:1:180;%now using this
            obj.num_angle = length(obj.aoa_angle); %now using this
            
            
            obj.num_byte_per_sample = 4; %try and figure out how to get from the JSON file
            obj.rx_chanl_enable = hex2poly(sys_param_json.mmWaveDevices.rfConfig.rlChanCfg_t.rxChannelEn);
            obj.num_rx_chnl = sum(obj.rx_chanl_enable);

            obj.num_sample_per_chirp = sys_param_json.mmWaveDevices.rfConfig.rlProfiles.rlProfileCfg_t.numAdcSamples;
            obj.num_chirp_per_frame = sys_param_json.mmWaveDevices.rfConfig.rlFrameCfg_t.numLoops;
            
            % coefficient for the Hanning window
            obj.win_hann = hanning(obj.num_sample_per_chirp);

            % size of one frame in Byte
            obj.size_per_frame = obj.num_byte_per_sample * obj.num_rx_chnl...
                                       * obj.num_sample_per_chirp * obj.num_chirp_per_frame;
                                   
           % get # of frames and samples per frame
            try
                bin_file = dir(adc_data_bin_file);
                bin_file_size = bin_file.bytes;
            catch
                error('Reading Bin file failed');
            end
            obj.num_frame = floor( bin_file_size/obj.size_per_frame );
            if obj.num_frame ~= sys_param_json.mmWaveDevices.rfConfig.rlFrameCfg_t.numFrames
                error('Computed # of frames not equal to that in the JSON file');
            end
            obj.num_sample_per_frame = obj.num_rx_chnl * obj.num_chirp_per_frame * obj.num_sample_per_chirp;

            % ADC specs
            obj.adc_samp_rate = sys_param_json.mmWaveDevices.rfConfig.rlProfiles.rlProfileCfg_t.digOutSampleRate/1000;
            if 2 == sys_param_json.mmWaveDevices.rfConfig.rlAdcOutCfg_t.fmt.b2AdcBits
                obj.adc_bits = 16;
            end
            obj.dbfs_coeff = - (20*log10(2.^(obj.adc_bits-1)) + 20*log10(sum(obj.win_hann)) - 20*log10(sqrt(2)));

            % chirp specs (MHz/usec)
            obj.chirp_slope = sys_param_json.mmWaveDevices.rfConfig.rlProfiles.rlProfileCfg_t.freqSlopeConst_MHz_usec;
            obj.bw = obj.chirp_slope * obj.num_sample_per_chirp / obj.adc_samp_rate;
            obj.chirp_ramp_time = sys_param_json.mmWaveDevices.rfConfig.rlProfiles.rlProfileCfg_t.rampEndTime_usec;
            obj.chirp_idle_time = sys_param_json.mmWaveDevices.rfConfig.rlProfiles.rlProfileCfg_t.idleTimeConst_usec;
            obj.chirp_adc_start_time = sys_param_json.mmWaveDevices.rfConfig.rlProfiles.rlProfileCfg_t.adcStartTimeConst_usec;
            obj.frame_periodicity = sys_param_json.mmWaveDevices.rfConfig.rlFrameCfg_t.framePeriodicity_msec;

            % range resolution
            obj.range_max = physconst('LightSpeed') * obj.adc_samp_rate*1e6 / (2*obj.chirp_slope*1e6*1e6);
            obj.range_res = physconst('LightSpeed') / (2*obj.bw*1e6);

            % velocity resolution
            obj.v_max = obj.lambda / (4*(obj.chirp_ramp_time + obj.chirp_idle_time)/1e6);
            obj.v_res = obj.lambda / (2*obj.num_chirp_per_frame*(obj.chirp_idle_time+obj.chirp_ramp_time)/1e6);

            % checking iqSwap setting
            obj.is_iq_swap = sys_param_json.mmWaveDevices.rawDataCaptureConfig.rlDevDataFmtCfg_t.iqSwapSel;
            % % Change Interleave data to non-interleave
            obj.is_interleave = sys_param_json.mmWaveDevices.rawDataCaptureConfig.rlDevDataFmtCfg_t.chInterleave;

        end
        
        function printDeviceConfiguration(obj)
            %printDeviceConfiguration prints out all info on the mmwave
            %device stored in the MMWaveDeviceClass
            fprintf('# of sample/chirp: %d\n', obj.num_sample_per_chirp);
            fprintf('# of chirp/frame: %d\n', obj.num_chirp_per_frame);
            fprintf('# of sample/frame: %d\n', obj.num_sample_per_frame);
            fprintf('Size of one frame: %d Bytes\n', obj.size_per_frame);
            fprintf('# of frames in the raw ADC data file: %d\n\n', obj.num_frame);

            fprintf('Rx channels enabled: [%s]\n',join(string(obj.rx_chanl_enable),','))
            fprintf('#of Rx channels: %d\n\n',obj.num_rx_chnl)

            fprintf('Radar bandwidth: %.2f (GHz)\n\n', obj.bw/1000);

            fprintf('ADC sampling rate: %.2f (MSa/s)\n', obj.adc_samp_rate);
            fprintf('ADC bits: %d bit\n', obj.adc_bits);
            fprintf('dBFS scaling factor: %.2f (dB)\n\n', obj.dbfs_coeff);

            fprintf('Chirp duration: %.2f (usec)\n', obj.chirp_idle_time+obj.chirp_ramp_time);
            fprintf('Chirp slope: %.2f (MHz/usec)\n', obj.chirp_slope);
            fprintf('Chirp bandwidth: %.2f (MHz)\n', obj.bw);
            fprintf('Chirp "valid" duration: %.2f (usec)\n\n', obj.num_sample_per_chirp/obj.adc_samp_rate);

            fprintf('Frame length: %.2f (msec)\n', obj.num_chirp_per_frame*(obj.chirp_idle_time+obj.chirp_ramp_time)/1000);
            fprintf('Frame periodicity: %.2f (msec)\n', obj.frame_periodicity);
            fprintf('Frame duty-cycle: %.2f \n\n', obj.num_chirp_per_frame*(obj.chirp_idle_time+obj.chirp_ramp_time)/1000/obj.frame_periodicity);

            fprintf('Range limit: %.4f (m)\n', obj.range_max);
            fprintf('Range resolution: %.4f (m)\n', obj.range_res);
            fprintf('Velocity limit: %.4f (m/s)\n', obj.v_max);
            fprintf('Velocity resolution: %.4f (m/s)\n\n', obj.v_res);

            fprintf('IQ swap?: %d\n', obj.is_iq_swap);
            fprintf('Interleaved data?: %d\n', obj.is_interleave);
            fprintf('...System configuration imported!\n\n')
        end
    end
end

