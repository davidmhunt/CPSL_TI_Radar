function [file_name] = GET_ADC_DATA_BIN_FILE(varargin)
%GET_ADC_DATA_BIN_FILE gets the adc_data.bin file
%   gets the adc_data.bin file that stores all of the raw data from the
%   DCA1000 board
%   Inputs:
%       varargin: can specify the file name and path if its already known
%   Outputs:
%       file_name: file name and path of the adc_data.bin file
    if nargin ~= 0
        file_name = varargin{1};
    else
        [file,path] = uigetfile('*.bin','Select adc_data.bin file');
        if isequal(file,0)
             fprintf('User selected Cancel \n');
             error('no .bin file selected')
        else
            fprintf('User selected %s \n',fullfile(path,file));
            file_name = fullfile(path,file);
        end
    end
end

