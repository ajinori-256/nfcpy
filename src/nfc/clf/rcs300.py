# -*- coding: latin-1 -*-
# -----------------------------------------------------------------------------
# Copyright 2026 ajinori-256
#
# Licensed under the EUPL, Version 1.1 or - as soon they
# will be approved by the European Commission - subsequent
# versions of the EUPL (the "Licence");
# You may not use this work except in compliance with the
# Licence.
# You may obtain a copy of the Licence at:
#
# https://joinup.ec.europa.eu/software/page/eupl
#
# Unless required by applicable law or agreed to in
# writing, software distributed under the Licence is
# distributed on an "AS IS" basis,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied.
# See the Licence for the specific language governing
# permissions and limitations under the Licence.
# -----------------------------------------------------------------------------
"""Driver module for contactless devices based on the Sony NFC
Port-400 chipset (PaSoRi RC-S300 series), speaking USB CCID with a
vendor-specific pseudo-APDU set carried in Escape commands.

==========  =========  =================================================
function    support    remarks
==========  =========  =================================================
sense_tta   no
sense_ttb   no
sense_ttf   yes
sense_dep   no
listen_*    no
==========  =========  =================================================

"""

import logging
import struct
from binascii import hexlify

import nfc.clf

from . import device

log = logging.getLogger(__name__)


class CCIDError(Exception):
    def __init__(self, status, error):
        self.status = status
        self.error = error

    def __str__(self):
        return "CCIDError(status=0x{:02x}, error=0x{:02x})".format(
            self.status, self.error
        )


class StatusError(Exception):
    def __init__(self, sw1, sw2):
        self.sw1 = sw1
        self.sw2 = sw2

    def __str__(self):
        return "SW={:02X}{:02X}".format(self.sw1, self.sw2)


class Chipset(object):
    PC_to_RDR_IccPowerOn = 0x62
    PC_to_RDR_IccPowerOff = 0x63
    PC_to_RDR_GetSlotStatus = 0x65
    PC_to_RDR_XfrBlock = 0x6F
    PC_to_RDR_GetParameters = 0x6C
    PC_to_RDR_ResetParameters = 0x6D
    PC_to_RDR_SetParameters = 0x61
    PC_to_RDR_Escape = 0x6B
    PC_to_RDR_IccClock = 0x6E
    PC_to_RDR_T0APDU = 0x6A
    PC_to_RDR_Secure = 0x69
    PC_to_RDR_Mechanical = 0x71
    PC_to_RDR_Abort = 0x72
    PC_to_RDR_SetDataRateAndClockFrequency = 0x73

    RDR_to_PC_DataBlock = 0x80
    RDR_to_PC_SlotStatus = 0x81
    RDR_to_PC_Parameters = 0x82
    RDR_to_PC_Escape = 0x83
    RDR_to_PC_DataRateAndClockFrequency = 0x84

    def __init__(self, transport, logger):
        self.transport = transport
        self.log = logger
        self._seq = 0
        self._slot = 0

        # Clear any response data that may be leftover from the last
        # session when it was killed.
        try:
            while True:
                data = self.transport.read(timeout=10)
                log.debug("cleared garbage %s", hexlify(data).decode())
        except IOError:
            pass

        # Basic initialization
        self.end_transparent_session()
        self.turn_off_rf()
        version = self.get_firmware_version()
        log.debug("firmware version %s", hexlify(version).decode())

    def close(self):
        try:
            self.turn_off_rf()
        except Exception:
            pass
        self.transport.close()
        self.transport = None

    def _next_seq(self):
        seq = self._seq
        self._seq = (self._seq + 1) % 256
        return seq

    def _ccid_escape(self, data):
        # Wrap the data (pseudo-APDU) in a PC_to_RDR_Escape message and send it,
        # returning the abData of RDR_to_PC_Escape
        seq = self._next_seq()
        header = struct.pack(
            "<BIBB3s",
            self.PC_to_RDR_Escape,
            len(data),
            self._slot,
            seq,
            b"\x00\x00\x00",
        )
        if self.transport is None:
            log.debug("transport closed in _ccid_escape")
            return None

        self.transport.write(header + bytes(data))
        response = bytearray(self.transport.read())

        if len(response) < 10:
            raise IOError("short CCID response ({} bytes)".format(len(response)))

        msg_type, length, slot, rseq, rfu = struct.unpack(
            "<BIBB3s", bytes(response[0:10])
        )

        if msg_type != self.RDR_to_PC_Escape:
            raise IOError("unexpected CCID message type 0x{:02x}".format(msg_type))
        if rseq != seq:
            log.warning("CCID sequence mismatch (sent %d, got %d)", seq, rseq)

        b_status, b_error = rfu[0], rfu[1]
        icc_status = b_status & 0x03
        cmd_status = b_status & 0xC0
        log.log(
            logging.DEBUG - 1,
            "bStatus=0x%02x (icc_status=%d) bError=0x%02x",
            b_status,
            icc_status,
            b_error,
        )
        if cmd_status == 0x40:
            raise CCIDError(b_status, b_error)

        return bytes(response[10 : 10 + length])

    def send_pseudo_apdu(self, ins, p1, p2, data=b"", le=0, extended=False):
        data = bytes(data)
        apdu = bytearray([0xFF, ins, p1, p2])

        if extended:
            apdu += b"\x00" + struct.pack(">H", len(data))
            apdu += data
            apdu += b"\x00" + struct.pack(">H", le & 0xFFFF)
        else:
            if data:
                apdu += bytes([len(data)]) + data
            apdu += bytes([le & 0xFF])

        log.log(logging.DEBUG - 1, "apdu %s", hexlify(apdu).decode())
        response = self._ccid_escape(apdu)
        if response is None:
            return None
        if len(response) < 2:
            raise IOError("pseudo-APDU response too short")

        sw1, sw2 = response[-2], response[-1]
        data = response[:-2]
        if (sw1, sw2) != (0x90, 0x00):
            raise StatusError(sw1, sw2)
        return data

    # -- confirmed high level commands ---------------------------------

    def get_firmware_version(self):
        return self.send_pseudo_apdu(0x56, 0x00, 0x00)

    def get_device_type(self):
        return self.send_pseudo_apdu(0x5F, 0x08, 0x00)

    def get_serial_number(self):
        return self.send_pseudo_apdu(0x5F, 0x03, 0x00)

    def start_transparent_session(self):
        self.send_pseudo_apdu(0x50, 0x00, 0x00, data=b"\x81\x00")

    def end_transparent_session(self):
        self.send_pseudo_apdu(0x50, 0x00, 0x00, data=b"\x82\x00")

    def turn_off_rf(self):
        self.send_pseudo_apdu(0x50, 0x00, 0x00, data=b"\x83\x00")

    def turn_on_rf(self):
        self.send_pseudo_apdu(0x50, 0x00, 0x00, data=b"\x84\x00")

    def set_protocol_type_a(self):
        self.send_pseudo_apdu(0x50, 0x00, 0x02, data=b"\x8f\x02\x00\x03")

    def set_protocol_type_f(self):
        self.send_pseudo_apdu(0x50, 0x00, 0x02, data=b"\x8f\x02\x03\x00")

    @staticmethod
    def _tlv_short(tag, value):
        return bytes(tag) + bytes([len(value)]) + bytes(value)

    @staticmethod
    def _tlv_ext(tag, value):
        return bytes(tag) + b"\x82" + struct.pack(">H", len(value)) + bytes(value)

    @staticmethod
    def _parse_tlvs(data):
        tlvs = {}
        i = 0
        data = bytes(data)
        while i < len(data):
            tag = data[i]
            i += 1
            length_byte = data[i]
            i += 1
            if length_byte < 0x80:
                length = length_byte
            elif length_byte == 0x81:
                length = data[i]
                i += 1
            elif length_byte == 0x82:
                length = (data[i] << 8) | data[i + 1]
                i += 2
            else:
                raise ValueError(
                    "unsupported TLV length encoding 0x{:02x}".format(length_byte)
                )
            tlvs[tag] = data[i : i + length]
            i += length
        return tlvs

    def communicate_thru_ex(self, transmit_data, timeout_ms=100):
        timeout_tlv = self._tlv_short(b"\x5f\x46", struct.pack("<I", timeout_ms * 1000))
        data_tlv = self._tlv_ext(b"\x95", bytes(transmit_data))
        body = timeout_tlv + data_tlv
        response = self.send_pseudo_apdu(
            0x50, 0x00, 0x01, data=body, le=0, extended=True
        )
        if not response:
            return None

        tlvs = self._parse_tlvs(response)

        result = tlvs.get(0xC0)
        if result and result[0] != 0:
            log.debug(
                "CommunicateThruEX result code 0x%02x (%s)",
                result[0],
                hexlify(result[1:]).decode(),
            )
            return None

        return tlvs.get(0x97)


class Device(device.Device):
    # Device driver for the Sony NFC Port-400 chipset (RC-S300).

    def __init__(self, chipset, logger):
        self.chipset = chipset
        self.log = logger
        self._chipset_name = "NFC Port-400 (RC-S300)"

    def close(self):
        self.chipset.close()
        self.chipset = None

    def mute(self):
        try:
            self.chipset.end_transparent_session()
        except Exception:
            pass
        self.chipset.turn_off_rf()

    def sense_tta(self, target):
        message = "{device} does not (yet) support sense for Type A Target"
        raise nfc.clf.UnsupportedTargetError(message.format(device=self))

    def sense_ttb(self, target):
        message = "{device} does not (yet) support sense for Type B Target"
        raise nfc.clf.UnsupportedTargetError(message.format(device=self))

    def sense_ttf(self, target):
        """Sense for a Type F Target is supported for 212 and 424 kbps."""
        if target.brty not in ("212F", "424F"):
            message = "unsupported bitrate {0}".format(target.brty)
            raise nfc.clf.UnsupportedTargetError(message)

        log.debug("polling for NFC-F technology")
        self.chipset.start_transparent_session()
        try:
            # Protocol type must be set before turning on the RF field.
            self.chipset.set_protocol_type_f()
            self.chipset.turn_on_rf()

            sensf_req = (
                target.sensf_req
                if target.sensf_req
                else bytearray.fromhex("00FFFF0100")
            )
            frame = bytearray([len(sensf_req) + 1]) + sensf_req

            frame = self.chipset.communicate_thru_ex(frame, timeout_ms=100)

            if not frame:
                self.chipset.end_transparent_session()
                return None

            log.debug("rcvd raw response %s", hexlify(frame).decode())

            sensf_res = None
            if len(frame) >= 18 and frame[0] == len(frame) and frame[1] == 1:
                sensf_res = frame[1:]
            elif len(frame) >= 17 and frame[0] == 1:
                sensf_res = frame

            if sensf_res is not None:
                log.debug("rcvd SENSF_RES %s", hexlify(sensf_res).decode())
                remote_target = nfc.clf.RemoteTarget(target.brty, sensf_res=sensf_res)
                return remote_target

            log.debug(
                "response does not look like a length-prefixed "
                "SENSF_RES, discarding (%s)",
                hexlify(frame).decode(),
            )
            self.chipset.end_transparent_session()
            return None
        except Exception:
            try:
                self.chipset.end_transparent_session()
            except Exception:
                pass
            raise

    def sense_dep(self, target):
        message = "{device} does not support sense for active DEP Target"
        raise nfc.clf.UnsupportedTargetError(message.format(device=self))

    def listen_tta(self, target, timeout):
        message = "{device} does not (yet) support listen as Type A Target"
        raise nfc.clf.UnsupportedTargetError(message.format(device=self))

    def listen_ttb(self, target, timeout):
        message = "{device} does not support listen as Type B Target"
        raise nfc.clf.UnsupportedTargetError(message.format(device=self))

    def listen_ttf(self, target, timeout):
        message = "{device} does not (yet) support listen as Type F Target"
        raise nfc.clf.UnsupportedTargetError(message.format(device=self))

    def listen_dep(self, target, timeout):
        message = "{device} does not (yet) support listen for DEP Target"
        raise nfc.clf.UnsupportedTargetError(message.format(device=self))

    def get_max_send_data_size(self, target):
        return 254

    def get_max_recv_data_size(self, target):
        return 254

    def send_cmd_recv_rsp(self, target, data, timeout):
        if timeout:
            timeout_ms = max(min(int(timeout * 1000), 0xFFFF), 1)
        else:
            timeout_ms = 0
        try:
            response = self.chipset.communicate_thru_ex(bytes(data), timeout_ms)

        except StatusError as error:
            log.debug(error)
            raise nfc.clf.TransmissionError(str(error))
        if response is None:
            raise nfc.clf.TimeoutError
        return response


def init(transport):
    chipset = Chipset(transport, logger=log)
    dev = Device(chipset, logger=log)
    dev._vendor_name = transport.manufacturer_name
    dev._device_name = transport.product_name
    return dev
