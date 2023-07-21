
% get the file and path of the adc_data.bin file
adc_data_file_name = '/Users/David/OneDrive - Duke University/Radar Security Project/Matlab Processing/Data Sets/intereference_feb_10_2022/PostProc/adc_data.bin';
adc_bin_file_name = GET_ADC_DATA_BIN_FILE(adc_data_file_name);
mmwave_setup_json_file_name = '/Users/David/OneDrive - Duke University/Radar Security Project/Matlab Processing/Data Sets/intereference_feb_10_2022/JSON/mmwave_setup.mmwave.json';
mmwave_json_file_name = GET_MMWAVE_SETUP_JSON_FILE(mmwave_setup_json_file_name);

%setup the mmwave_device_params
mmwave_device = MMWaveDevice(adc_bin_file_name,mmwave_json_file_name);
%mmwave_device.printDeviceConfiguration()

%setup the ADCData Class
adc_data = ADCData(adc_bin_file_name,mmwave_device);

%plot the data from LVDS channel 2 or frame 1 from chirp 1
%adc_data.frames(1).chirps(1).plot(2);

%take the fft of the first chirp
chirp = adc_data.frames(292).chirps(1).chirp_data(1,:);
fft_ = 20 * log10(abs(fft(chirp)));


ranges = (0:mmwave_device.num_sample_per_chirp - 1) * mmwave_device.range_res;
plot(ranges,abs(fft_))

% range_fft = fft(chirp,2^(nextpow2(size(chirp,2))));
% range_fft = range_fft(1:0.5*size(range_fft,2));
% range_fft = 20*log10(abs(range_fft)) + mmwave_device.dbfs_coeff;
% 
% %num_samples = mmwave_device.num_sample_per_chirp;
% num_samples = size(range_fft,2);
% sample_freq = mmwave_device.adc_samp_rate * 10^6; %in Hz
% f_bins = (0:1/num_samples: 1 - 1/num_samples) * sample_freq;
% 
% c = physconst('LightSpeed'); %in m/s
% chirp_slope = mmwave_device.chirp_slope * 10^6* 10^6; %in Hz/s
% d_bins = f_bins * c / (2 * chirp_slope);
% plot(d_bins, range_fft);
% grid on;