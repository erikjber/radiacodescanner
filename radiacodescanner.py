"""A command-line tool to extract spectrums from a Radiacode device using Bluetooth"""
import argparse
import asyncio
import datetime
import struct
from lxml import etree
from bleak import BleakScanner, BleakClient

RC_BLE_SERVICE = "e63215e5-7003-49d8-96b0-b024798fb901"
RC_BLE_CHARACTERISTIC = "e63215e6-7003-49d8-96b0-b024798fb901"
RC_BLE_NOTIFY = "e63215e7-7003-49d8-96b0-b024798fb901"
RC_GET_SPECTRUM = b'\x08\x00\x00\x00&\x08\x00\x80\x00\x02\x00\x00'

buffer = bytearray()

class RadiaCodeSpectrum:
    """Class to parse and save Radiacode spectrum data."""
    NSMAP = {
        "xsd": "http://www.w3.org/2001/XMLSchema",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    def __init__(self, device_name:str, device_serial:str, databuffer:bytearray):
        """This code is heavily based on the BecqMoni program by Am6er: https://github.com/Am6er/BecqMoni"""
        self.device_name = device_name
        self.device_serial = device_serial
        size = struct.unpack("<i",databuffer[0:4])[0]+4
        if size != len(databuffer):
            raise RuntimeError(f"Incorrect size of radiacode spectrum, should be {size} bytes but was "
                               f"{len(databuffer)} bytes instead.Please try again.")
        self.time = struct.unpack('<I', databuffer[16:20])[0]
        # Get the calibration coefficients
        self.coefficients = [0,0,0]
        self.coefficients[0] = struct.unpack("<f", databuffer[20:24])[0]
        self.coefficients[1] = struct.unpack("<f", databuffer[24:28])[0]
        self.coefficients[2] = struct.unpack("<f", databuffer[28:32])[0]

        # Guesstimate the start and end times
        self.spectrum_recording_end = datetime.datetime.now(datetime.timezone.utc)
        self.spectrum_recording_start = self.spectrum_recording_end-datetime.timedelta(seconds=self.time)

        # Parse the data
        last_value = 0
        i = 32
        self.data = []
        while i < size:
            position = ((databuffer[i+1] & 0xFF) << 8) | (databuffer[i] & 0xFF)
            i = i + 2
            count_occurrences = (position >> 4) & 0x0FFF
            var_length = position & 0x0F
            for _ in range(count_occurrences):
                match var_length:
                    case 0:
                        result = 0
                    case 1:
                        result = databuffer[i] & 0xFF
                        i = i + 1
                    case 2:
                        result = last_value + struct.unpack("<b", databuffer[i:i+1])[0]
                        i = i + 1
                    case 3:
                        result = last_value + struct.unpack("<h",databuffer[i:i+2])[0]
                        i = i + 2
                    case 4:
                        result = ((databuffer[i + 2] & 0xFF) << 16) | ((databuffer[i + 1] & 0xFF) << 8)
                        result |= (databuffer[i] & 0xFF)
                        result &= 0xFFFFFF
                        result += last_value
                        i = i + 3
                    case 5:
                        result = ((databuffer[i + 3] & 0xFF) << 24) | ((databuffer[i + 2] & 0xFF) << 16)
                        result |= ((databuffer[i + 1] & 0xFF) << 8) | (databuffer[i] & 0xFF)
                        result &= 0xFFFFFF
                        result += last_value
                        i = i + 4
                    case _:
                        raise RuntimeError(f"Something went wrong, var_lenght is {var_length}")
                last_value = result
                self.data.append(result)

    def dump_xml(self, filename, spectrumname) -> None:
        """Write the spectrum to an XML file suitable for import to, for example, InterSpec."""
        root = etree.Element("ResultDataFile",nsmap=RadiaCodeSpectrum.NSMAP)
        etree.SubElement(root, "FormatVersion").text = "120920"
        resultdatalist = etree.SubElement(root, "ResultDataList")
        resultdata = etree.SubElement(resultdatalist, "ResultData")
        deviceconfig = etree.SubElement(resultdata, "DeviceConfigReference")
        etree.SubElement(deviceconfig, "Name").text = self.device_name
        sampleinfo = etree.SubElement(resultdata, "SampleInfo")
        etree.SubElement(sampleinfo, "Name").text = etree.CDATA(spectrumname)
        etree.SubElement(sampleinfo, "Note").text = etree.CDATA("")

        # We don't have the background spectrum, so we leave this entry empty
        etree.SubElement(resultdata, "BackgroundSpectrumFile").text = etree.CDATA("")

        etree.SubElement(resultdata, "StartTime").text = self.spectrum_recording_start.strftime("%Y-%m-%dT%H:%M:%S")
        etree.SubElement(resultdata, "EndTime").text = self.spectrum_recording_end.strftime("%Y-%m-%dT%H:%M:%S")
        energyspectrum = etree.SubElement(resultdata, "EnergySpectrum")
        etree.SubElement(energyspectrum, "NumberOfChannels").text = str(len(self.data))
        etree.SubElement(energyspectrum, "ChannelPitch").text = "1"
        etree.SubElement(energyspectrum, "SpectrumName").text =  etree.CDATA(spectrumname)
        etree.SubElement(energyspectrum, "Comment")
        etree.SubElement(energyspectrum, "SerialNumber").text = self.device_serial
        energycalibration = etree.SubElement(energyspectrum, "EnergyCalibration")
        etree.SubElement(energycalibration, "PolynomialOrder").text = "2"
        coefficients = etree.SubElement(energycalibration, "Coefficients")
        for coefficient in self.coefficients:
            etree.SubElement(coefficients, "Coefficient").text = f"{coefficient:.7E}"
        etree.SubElement(energyspectrum, "MeasurementTime").text = str(self.time)
        etree.SubElement(energyspectrum, "LiveTime").text = str(self.time)
        spectrum = etree.SubElement(energyspectrum, "Spectrum")
        for d in self.data:
            etree.SubElement(spectrum, "DataPoint").text = str(d)
        etree.SubElement(resultdata, "Visible").text = "true"

        #These entries don't contain any data, but is included here for maximum compatibility
        pulsecollection = etree.SubElement(resultdata, "PulseCollection")
        etree.SubElement(pulsecollection, "Format").text = "Base64 encoded binary"
        etree.SubElement(pulsecollection, "Pulses")

        tree = etree.ElementTree(root)
        tree.write(filename,xml_declaration=True,encoding="utf-8",pretty_print=True)

def print_if(string:str,condition:bool) -> None:
    """Print the string iff condition is True."""
    if condition:
        print(string)

async def main(args) -> None:
    """Program entry point."""
    if args.serial:
        print_if(f"Scanning for Radiacode devices with serial number {args.serial}...", not args.quiet)
    else:
        print_if("Scanning for Radiacode devices...", not args.quiet)
    devices = await BleakScanner.discover()
    radiacode_devices = []
    for d in devices:
        if d.name and d.name.lower().startswith("radiacode"):
            radiacode_devices.append(d)
    if not radiacode_devices:
        print("No Radiacode devices found!")
        print("Make sure your device is turned on, within range, and not connected to any other device.")
    else:
        # At least one device was found
        if args.serial:
            found = False
            for d in radiacode_devices:
                serial = d.name.split("#")[1]
                if serial.lower() == args.serial.lower():
                    found = True
                    print_if(f"Connecting to {d}", not args.quiet)
                    await save_spectrum(d,args,"spectrum dumped from radiacode")
                else:
                    print_if(f"Ignoring device with serial {serial}",not args.quiet)
            if not found:
                print(f"No radiacode devices with serial {args.serial} found!")
                print("Make sure your device is turned on, within range, and not connected to any other device.")
        elif len(radiacode_devices) == 1:
            # No serial but only one device found
            d = radiacode_devices[0]
            print_if(f"Connecting to {d}", not args.quiet)
            await save_spectrum(d,args,"spectrum dumped from radiacode")
        else:
            # No serial but more than once device found
            print(f"Found {len(radiacode_devices)} radiacode devices, please specify serial number.")
            print("Available radiacode devices:")
            for d in radiacode_devices:
                print(d)

def callback(_, data:bytearray) -> None:
    """Add the data received from the radiacode device to the data buffer."""
    buffer.extend(data)

def format_time(seconds:int) -> str:
    """Format elapsed time to a human-readable string."""
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    result = ""
    if days > 0:
        result += f"{days} day"
        if days > 1:
            result += "s"
    if hours > 0:
        if len(result) > 0:
            result += ", "
        result += f"{hours} hour"
        if hours > 1:
            result += "s"
    if minutes > 0:
        if len(result) > 0:
            result += ", "
        result += f"{minutes} minute"
        if minutes > 1:
            result += "s"
    if seconds > 0:
        if len(result) > 0:
            result += ", "
        result += f"{seconds} second"
        if seconds > 1:
            result += "s"
    return result

async def save_spectrum(device,args,spectrumname) -> None:
    """Save the spectrum to the filename  given by args.file"""
    parts = device.name.split("#")
    name = parts[0]
    serial = parts[1]
    buffer.clear()
    async with BleakClient(device.address) as client:
        service = get_service(client,RC_BLE_SERVICE)
        characteristic = service.get_characteristic(RC_BLE_CHARACTERISTIC)
        notify_characteristic = service.get_characteristic(RC_BLE_NOTIFY)
        await client.start_notify(notify_characteristic, callback)
        await client.write_gatt_char(characteristic, RC_GET_SPECTRUM,response=True)
        try:
            await client.disconnect()
        except EOFError as e:
            print(f"EOFError when disconnecting: {e}")
    spectrum = RadiaCodeSpectrum(name,serial,buffer)
    if not args.quiet:
        print(f"Spectrum collected over {format_time(spectrum.time)}.")
    spectrum.dump_xml(args.file,spectrumname)

def get_service(client,service_uuid):
    """Get the GATT service with the given UUID."""
    for service in client.services:
        if service.uuid == service_uuid:
            return service
    return None

def parse_args():
    """Parse and return the command line arguments."""
    parser = argparse.ArgumentParser(
        description="Scan RadiaCode devices for gamma spectra and save to XML format.",
        epilog="This program is in no way associated with or endorsed by the Radiacode Ltd company.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-f","--file",help="Specify the radiacode spectrum output filename. "
                                           "You can use relative or absolute paths.",type=str,default="output.xml")
    parser.add_argument("-s","--serial",help="Specify the radiacode device serial number. "
                                             "Case insensitive. Ignored if not given and only one device is found. "
                                             "Omit this if you only have one device.",type=str, required=False)
    parser.add_argument("-q","--quiet",help="No console output unless something goes wrong.",
                        action="store_true")
    return parser.parse_args()

if __name__ == "__main__":
    asyncio.run(main(parse_args()))
