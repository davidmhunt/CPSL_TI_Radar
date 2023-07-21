function ret_adc_data = READ_ADC_DATA_BIN_FILE(adc_data_bin_file,mmWave_device)
    %Function to read the adc_data.bin file and sort the data into
    %individual LVDS lanes
    %
    %Variables
    %   adc_data_bin_file - the path to the adc_data.bin file
    %   mmWave_device - an MMWAVEDEVICE class object with
    %       information on the device itself
    %
    %Returns:
    %   ret_adc_data - the complex adc samples for each channel
    %% global variables
        numADCBits = mmWave_device.adc_bits; % number of ADC bits per sample
        numLanes = 4; % do not change. number of lanes is always 4 even if only 1 lane is used. unused lanes
        isReal = 0; % set to 1 if real only data, 0 if complex data are populated with 0

    %% read file and convert to signed number
        % read .bin file
        fid = fopen(adc_data_bin_file,'r');
        % DCA1000 should read in two's complement data
        adc_data = fread(fid, 'int16');
        % if 12 or 14 bits ADC per sample compensate for sign extension
        if numADCBits ~= 16
            l_max = 2^(numADCBits-1)-1;
            adc_data(adc_data > l_max) = adc_data(adc_data > l_max) - 2^numADCBits;
        end
        fclose(fid);
    %% organize data by LVDS lane
        % for real only data
        if isReal
            % reshape data based on one samples per LVDS lane
            adc_data = reshape(adc_data, numLanes, []);
        %for complex data
        else
            % reshape and combine real and imaginary parts of complex number
            adc_data = reshape(adc_data, numLanes*2, []);
            adc_data = adc_data([1,2,3,4],:) + sqrt(-1)*adc_data([5,6,7,8],:);
        end
    %% return receiver data
    ret_adc_data = adc_data;
end