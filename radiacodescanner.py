import argparse
import asyncio
import datetime
import struct

from lxml import etree

from bleak import BleakScanner, BleakClient

RC_BLE_Service = "e63215e5-7003-49d8-96b0-b024798fb901"
RC_BLE_Characteristic = "e63215e6-7003-49d8-96b0-b024798fb901"
RC_BLE_Notify = "e63215e7-7003-49d8-96b0-b024798fb901"
RC_GET_SPECTRUM = b'\x08\x00\x00\x00&\x08\x00\x80\x00\x02\x00\x00'

buffer = bytearray()


class RadiaCodeSpectrum:
    """Class to parse and save Radiacode spectrum data."""
    NSMAP = {
        "xsd": "http://www.w3.org/2001/XMLSchema",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    }

    def __init__(self, device_name:str, device_serial:str, buffer:bytearray):
        """This code is heavily based on the BecqMoni program by Am6er: https://github.com/Am6er/BecqMoni"""
        self.device_name = device_name
        self.device_serial = device_serial
        self.size = struct.unpack("<i",buffer[0:4])[0]+4
        if self.size != len(buffer):
            raise RuntimeError(f"Incorrect size of radiacode spectrum, should be {self.size} bytes but was {len(buffer)} bytes instead.Please try again.")
        self.time = struct.unpack('<I', buffer[16:20])[0]
        # Get the calibration coefficients
        self.a0 = struct.unpack("<f", buffer[20:24])[0]
        self.a1 = struct.unpack("<f", buffer[24:28])[0]
        self.a2 = struct.unpack("<f", buffer[28:32])[0]

        # Guesstimate the start and end times
        self.spectrum_recording_end = datetime.datetime.now(datetime.timezone.utc)
        self.spectrum_recording_start = self.spectrum_recording_end-datetime.timedelta(seconds=self.time)

        # Parse the data
        last_value = 0
        i = 32
        self.data = []
        while i < self.size:
            position = ((buffer[i+1] & 0xFF) << 8) | (buffer[i] & 0xFF)
            i = i + 2
            count_occurences = (position >> 4) & 0x0FFF
            var_lenght = position & 0x0F
            for j in range(count_occurences):
                match var_lenght:
                    case 0:
                        result = 0
                    case 1:
                        result = (buffer[i] & 0xFF)
                        i = i + 1
                    case 2:
                        result = last_value + struct.unpack("<b", buffer[i:i+1])[0]
                        i = i + 1
                    case 3:
                        result = last_value + struct.unpack("<h",buffer[i:i+2])[0]
                        i = i + 2
                    case 4:
                        result = last_value + (((buffer[i + 2] & 0xFF) << 16) | ((buffer[i + 1] & 0xFF) << 8) | (buffer[i] & 0xFF)) & 0xFFFFFF
                        i = i + 3
                    case 5:
                        result = last_value + (((buffer[i + 3] & 0xFF) << 24) | ((buffer[i + 2] & 0xFF) << 16) | ((buffer[i + 1] & 0xFF) << 8) | (buffer[i] & 0xFF)) & 0xFFFFFF
                        i = i + 4
                    case _:
                        raise RuntimeError(f"Something went wrong, var_lenght is {var_lenght}")
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
        etree.SubElement(coefficients, "Coefficient").text = f"{self.a0:.7E}"
        etree.SubElement(coefficients, "Coefficient").text = f"{self.a1:.7E}"
        etree.SubElement(coefficients, "Coefficient").text = f"{self.a2:.7E}"
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

async def main(args) -> None:
    if not args.quiet:
        if args.serial:
            print(f"Scanning for Radiacode devices with serial number {args.serial}...")
        else:
            print("Scanning for Radiacode devices...")
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
                    if not args.quiet:
                        print(f"Connecting to {d}")
                    await save_spectrum(d,args,"spectrum dumped from radiacode")
                elif not args.quiet:
                    print(f"Ignoring device with serial {serial}")
            if not found:
                print(f"No radiacode devices with serial {args.serial} found!")
                print("Make sure your device is turned on, within range, and not connected to any other device.")
        elif len(radiacode_devices) == 1:
            # No serial but only one device found
            d = radiacode_devices[0]
            if not args.quiet:
                print(f"Connecting to {d}")
            await save_spectrum(d,args,"spectrum dumped from radiacode")
        else:
            # No serial but more than once device found
            print(f"Found {len(radiacode_devices)} radiacode devices, please specify serial number.")
            print("Available radiacode devices:")
            for d in radiacode_devices:
                print(d)


def callback(sender, data:bytearray) -> None:
    buffer.extend(data)

def format_time(seconds:int) -> str:
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
    parts = device.name.split("#")
    name = parts[0]
    serial = parts[1]
    buffer.clear()
    async with BleakClient(device.address) as client:
        service = get_service(client,RC_BLE_Service)
        characteristic = service.get_characteristic(RC_BLE_Characteristic)
        notify_characteristic = service.get_characteristic(RC_BLE_Notify)
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


def get_service(client,service):
    for service in client.services:
        if service.uuid == RC_BLE_Service:
            return service
    return None

def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan RadiaCode devices for gamma spectra and save to XML format.",
        epilog="This program is in no way associated with or endorsed by the Radiacode Ltd company or any of its subsidiaries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-f","--file",help="Specify the radiacode spectrum output filename. You can use relative or absolute paths.",type=str,default="output.xml")
    parser.add_argument("-s","--serial",help="Specify the radiacode device serial number. Case insensitive. Ignored if not given and only one device is found. Omit this if you only have one device.",type=str, required=False)
    parser.add_argument("-q","--quiet",help="No console output unless something goes wrong.",action="store_true")
    return parser.parse_args()

if __name__ == "__main__":
    asyncio.run(main(parse_args()))
