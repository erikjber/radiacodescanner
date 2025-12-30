A simple, one-file Python program to save the spectrum from a [RadiaCode](https://www.radiacode.com/) device to an XML file using Bluetooth.  

RadiaCode devices are great, but to get the spectrum from the device to your computer you either have to use a Windows-only program
or go via a mobile device. If you are using Linux this can be cumbersome.
This simple command-line utility lets you dump the spectrum directly to an XML file suitable for spectrum analysis programs, e.g. [InterSpec](https://sandialabs.github.io/InterSpec/). 

This program is, in part, based on [BecqMoni by Am6er](https://github.com/Am6er/BecqMoni).

## Installation
```
pip install lxml
pip install bleak
```
Save the file radiacodescanner.py on your computer and run this command:
```
python radiacodescanner.py
```

## Command line options
```
  -h, --help           show this help message and exit
  -f, --file FILE      Specify the radiacode spectrum output filename. You can
                       use relative or absolute paths. (default: output.xml)
  -s, --serial SERIAL  Specify the radiacode device serial number. Case
                       insensitive. Ignored if not given and only one device
                       is found. Omit this if you only have one device.
                       (default: None)
  -q, --quiet          No console output unless something goes wrong.
                       (default: False)
```

## Disclaimer
This program is in no way associated with or endorsed by the Radiacode Ltd company or any of its subsidiaries. 
