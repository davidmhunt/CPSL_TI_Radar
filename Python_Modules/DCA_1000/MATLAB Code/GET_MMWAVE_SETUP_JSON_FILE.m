function [file_name] = GET_MMWAVE_SETUP_JSON_FILE(varargin)
%GET_MMWAVE_SETUP_JSON_FILE gets the mmwave.json file
%   gets the mmwave.json file that stores configuration information for the
%   IWR1443 board
%   Inputs:
%       varargin: can specify the file name and path if its already known
%   Outputs:
%       file_name: file name and path of the mmwave.json file
    if nargin ~= 0
        file_name = varargin{1};
    else
        [file,path] = uigetfile('*.JSON','Select mmwave_setup JSON file');
        if isequal(file,0)
             fprintf('User selected Cancel \n');
             error('no .JSON file selected')
        else
            fprintf('User selected %s \n',fullfile(path,file));
            file_name = fullfile(path,file);
        end
    end
end

