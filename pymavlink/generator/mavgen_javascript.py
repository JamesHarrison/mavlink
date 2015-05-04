#!/usr/bin/env python
'''
parse a MAVLink protocol XML file and generate a Node.js javascript module implementation

Based on original work Copyright Andrew Tridgell 2011
Released under GNU GPL version 3 or later
'''

import sys
import textwrap
import os
from . import mavparse, mavtemplate
from shutil import copyfile

t = mavtemplate.MAVTemplate()


def generate_preamble(outf, msgs, args, xml):
    print("Generating preamble")
    t.write(outf, """
/*
MAVLink protocol implementation for node.js (auto-generated by mavgen_javascript.py)

Generated from: ${FILELIST}

Note: this file has been auto-generated. DO NOT EDIT
*/

jspack = require("./jspack.js").jspack,
    _ = require("underscore"),
    events = require("events"),
    util = require("util");

// Add a convenience method to Buffer
Buffer.prototype.toByteArray = function () {
  return Array.prototype.slice.call(this, 0)
}

mavlink = function(){};

// Implement the X25CRC function (present in the Python version through the mavutil.py package)
mavlink.x25Crc = function(buffer, crc) {

    var bytes = buffer;
    var crc = crc || 0xffff;
    _.each(bytes, function(e) {
        var tmp = e ^ (crc & 0xff);
        tmp = (tmp ^ (tmp << 4)) & 0xff;
        crc = (crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4);
        crc = crc & 0xffff;
    });
    return crc;

}

mavlink.WIRE_PROTOCOL_VERSION = "${WIRE_PROTOCOL_VERSION}";

mavlink.MAVLINK_TYPE_CHAR     = 0
mavlink.MAVLINK_TYPE_UINT8_T  = 1
mavlink.MAVLINK_TYPE_INT8_T   = 2
mavlink.MAVLINK_TYPE_UINT16_T = 3
mavlink.MAVLINK_TYPE_INT16_T  = 4
mavlink.MAVLINK_TYPE_UINT32_T = 5
mavlink.MAVLINK_TYPE_INT32_T  = 6
mavlink.MAVLINK_TYPE_UINT64_T = 7
mavlink.MAVLINK_TYPE_INT64_T  = 8
mavlink.MAVLINK_TYPE_FLOAT    = 9
mavlink.MAVLINK_TYPE_DOUBLE   = 10

// Mavlink headers incorporate sequence, source system (platform) and source component.
mavlink.header = function(msgId, mlen, seq, srcSystem, srcComponent) {

    this.mlen = ( typeof mlen === 'undefined' ) ? 0 : mlen;
    this.seq = ( typeof seq === 'undefined' ) ? 0 : seq;
    this.srcSystem = ( typeof srcSystem === 'undefined' ) ? 0 : srcSystem;
    this.srcComponent = ( typeof srcComponent === 'undefined' ) ? 0 : srcComponent;
    this.msgId = msgId

}

mavlink.header.prototype.pack = function() {
    return jspack.Pack('BBBBBB', [${PROTOCOL_MARKER}, this.mlen, this.seq, this.srcSystem, this.srcComponent, this.msgId]);
}

// Base class declaration: mavlink.message will be the parent class for each
// concrete implementation in mavlink.messages.
mavlink.message = function() {};

// Convenience setter to facilitate turning the unpacked array of data into member properties
mavlink.message.prototype.set = function(args) {
    _.each(this.fieldnames, function(e, i) {
        this[e] = args[i];
    }, this);
};

// This pack function builds the header and produces a complete MAVLink message,
// including header and message CRC.
mavlink.message.prototype.pack = function(mav, crc_extra, payload) {

    this.payload = payload;
    this.header = new mavlink.header(this.id, payload.length, mav.seq, mav.srcSystem, mav.srcComponent);
    this.msgbuf = this.header.pack().concat(payload);
    var crc = mavlink.x25Crc(this.msgbuf.slice(1));

    // For now, assume always using crc_extra = True.  TODO: check/fix this.
    crc = mavlink.x25Crc([crc_extra], crc);
    this.msgbuf = this.msgbuf.concat(jspack.Pack('<H', [crc] ) );
    return this.msgbuf;

}

""", {'FILELIST' : ",".join(args),
      'PROTOCOL_MARKER': xml.protocol_marker,
      'crc_extra': xml.crc_extra,
      'WIRE_PROTOCOL_VERSION': xml.wire_protocol_version})


def generate_enums(outf, enums):
    print("Generating enums")
    outf.write("\n// enums\n")
    wrapper = textwrap.TextWrapper(
        initial_indent="",
        subsequent_indent="                        // ")
    for e in enums:
        outf.write("\n// %s\n" % e.name)
        for entry in e.entry:
            outf.write(
                "mavlink.%s = %u // %s\n" %
                (entry.name,
                 entry.value,
                 wrapper.fill(
                     entry.description)))


def generate_message_ids(outf, msgs):
    print("Generating message IDs")
    outf.write("\n// message IDs\n")
    outf.write("mavlink.MAVLINK_MSG_ID_BAD_DATA = -1\n")
    for m in msgs:
        outf.write("mavlink.MAVLINK_MSG_ID_%s = %u\n" % (m.name.upper(), m.id))


def generate_classes(outf, msgs):
    """
    Generate the implementations of the classes representing MAVLink messages.

    """
    print("Generating class definitions")
    wrapper = textwrap.TextWrapper(initial_indent="", subsequent_indent="")
    outf.write("\nmavlink.messages = {};\n\n")

    def field_descriptions(fields):
        ret = ""
        for f in fields:
            ret += "                %-18s        : %s (%s)\n" % (
                f.name, f.description.strip(), f.type)
        return ret

    for m in msgs:

        comment = "%s\n\n%s" % (wrapper.fill(
            m.description.strip()),
            field_descriptions(
            m.fields))

        selffieldnames = 'self, '
        for f in m.fields:
            # if f.omit_arg:
            #    selffieldnames += '%s=%s, ' % (f.name, f.const_value)
            # else:
            # -- Omitting the code above because it is rarely used (only once?) and would need some special handling
            # in javascript.  Specifically, inside the method definition, it needs to check for a value then assign
            # a default.
            selffieldnames += '%s, ' % f.name
        selffieldnames = selffieldnames[:-2]

        sub = {'NAMELOWER': m.name.lower(),
               'SELFFIELDNAMES': selffieldnames,
               'COMMENT': comment,
               'FIELDNAMES': ", ".join(m.fieldnames)}

        t.write(outf, """
/*
${COMMENT}
*/
""", sub)

        # function signature + declaration
        outf.write("mavlink.messages.%s = function(" % (m.name.lower()))
        if len(m.fields) != 0:
            outf.write(", ".join(m.fieldnames))
        outf.write(") {")

        # body: set message type properties
        outf.write("""

    this.format = '%s';
    this.id = mavlink.MAVLINK_MSG_ID_%s;
    this.order_map = %s;
    this.crc_extra = %u;
    this.name = '%s';

""" % (m.fmtstr, m.name.upper(), m.order_map, m.crc_extra, m.name.upper()))

        # body: set own properties
        if len(m.fieldnames) != 0:
            outf.write(
                "    this.fieldnames = ['%s'];\n" %
                "', '".join(
                    m.fieldnames))
        outf.write("""

    this.set(arguments);

}
        """)

        # inherit methods from the base message class
        outf.write("""
mavlink.messages.%s.prototype = new mavlink.message;
""" % m.name.lower())

        # Implement the pack() function for this message
        outf.write("""
mavlink.messages.%s.prototype.pack = function(mav) {
    return mavlink.message.prototype.pack.call(this, mav, this.crc_extra, jspack.Pack(this.format""" % m.name.lower())
        if len(m.fields) != 0:
            outf.write(
                ", [ this." +
                ", this.".join(
                    m.ordered_fieldnames) +
                ']')
        outf.write("));\n}\n\n")


def mavfmt(field):
    '''work out the struct format for a type'''
    map = {
        'float': 'f',
        'double': 'd',
        'char': 'c',
        'int8_t': 'b',
        'uint8_t': 'B',
        'uint8_t_mavlink_version': 'B',
        'int16_t': 'h',
        'uint16_t': 'H',
        'int32_t': 'i',
        'uint32_t': 'I',
        'int64_t': 'q',
        'uint64_t': 'Q',
    }

    if field.array_length:
        if field.type in ['char', 'int8_t', 'uint8_t']:
            return str(field.array_length) + 's'
        return str(field.array_length) + map[field.type]
    return map[field.type]


def generate_mavlink_class(outf, msgs, xml):
    print("Generating MAVLink class")

    # Write mapper to enable decoding based on the integer message type
    outf.write("\n\nmavlink.map = {\n")
    for m in msgs:
        outf.write(
            "        %s: { format: '%s', type: mavlink.messages.%s, order_map: %s, crc_extra: %u },\n" %
            (m.id, m.fmtstr, m.name.lower(), m.order_map, m.crc_extra))
    outf.write("}\n\n")

    t.write(outf, """

// Special mavlink message to capture malformed data packets for debugging
mavlink.messages.bad_data = function(data, reason) {
    this.id = mavlink.MAVLINK_MSG_ID_BAD_DATA;
    this.data = data;
    this.reason = reason;
    this.msgbuf = data;
}

/* MAVLink protocol handling class */
MAVLink = function(logger, srcSystem, srcComponent) {

    this.logger = logger;

    this.seq = 0;
    this.buf = new Buffer(0);
    this.bufInError = new Buffer(0);

    this.srcSystem = (typeof srcSystem === 'undefined') ? 0 : srcSystem;
    this.srcComponent =  (typeof srcComponent === 'undefined') ? 0 : srcComponent;

    // The first packet we expect is a valid header, 6 bytes.
    this.expected_length = 6;

    this.have_prefix_error = false;

    this.protocol_marker = 254;
    this.little_endian = true;

    this.crc_extra = true;
    this.sort_fields = true;
    this.total_packets_sent = 0;
    this.total_bytes_sent = 0;
    this.total_packets_received = 0;
    this.total_bytes_received = 0;
    this.total_receive_errors = 0;
    this.startup_time = Date.now();

}

// Implements EventEmitter
util.inherits(MAVLink, events.EventEmitter);

// If the logger exists, this function will add a message to it.
// Assumes the logger is a winston object.
MAVLink.prototype.log = function(message) {
    if(this.logger) {
        this.logger.info(message);
    }
}

MAVLink.prototype.log = function(level, message) {
    if(this.logger) {
        this.logger.log(level, message);
    }
}

MAVLink.prototype.send = function(mavmsg) {
    buf = mavmsg.pack(this);
    this.file.write(buf);
    this.seq = (this.seq + 1) % 256;
    this.total_packets_sent +=1;
    this.total_bytes_sent += buf.length;
}

// return number of bytes needed for next parsing stage
MAVLink.prototype.bytes_needed = function() {
    ret = this.expected_length - this.buf.length;
    return ( ret <= 0 ) ? 1 : ret;
}

// add data to the local buffer
MAVLink.prototype.pushBuffer = function(data) {
    if(data) {
        this.buf = Buffer.concat([this.buf, data]);
        this.total_bytes_received += data.length;
    }
}

// Decode prefix.  Elides the prefix.
MAVLink.prototype.parsePrefix = function() {

    // Test for a message prefix.
    if( this.buf.length >= 1 && this.buf[0] != 254 ) {

        // Strip the offending initial byte and throw an error.
        var badPrefix = this.buf[0];
        this.bufInError = this.buf.slice(0,1);
        this.buf = this.buf.slice(1);
        this.expected_length = 6;

        // TODO: enable subsequent prefix error suppression if robust_parsing is implemented
        //if(!this.have_prefix_error) {
        //    this.have_prefix_error = true;
            throw new Error("Bad prefix ("+badPrefix+")");
        //}

    }
    //else if( this.buf.length >= 1 && this.buf[0] == 254 ) {
    //    this.have_prefix_error = false;
    //}

}

// Determine the length.  Leaves buffer untouched.
MAVLink.prototype.parseLength = function() {

    if( this.buf.length >= 2 ) {
        var unpacked = jspack.Unpack('BB', this.buf.slice(0, 2));
        this.expected_length = unpacked[1] + 8; // length of message + header + CRC
    }

}

// input some data bytes, possibly returning a new message
MAVLink.prototype.parseChar = function(c) {

    var m = null;

    try {

        this.pushBuffer(c);
        this.parsePrefix();
        this.parseLength();
        m = this.parsePayload();

    } catch(e) {

        this.log('error', e.message);
        this.total_receive_errors += 1;
        m = new mavlink.messages.bad_data(this.bufInError, e.message);
        this.bufInError = new Buffer(0);

    }

    if(null != m) {
        this.emit(m.name, m);
        this.emit('message', m);
    }

    return m;

}

MAVLink.prototype.parsePayload = function() {

    var m = null;

    // If we have enough bytes to try and read it, read it.
    if( this.expected_length >= 8 && this.buf.length >= this.expected_length ) {

        // Slice off the expected packet length, reset expectation to be to find a header.
        var mbuf = this.buf.slice(0, this.expected_length);
        // TODO: slicing off the buffer should depend on the error produced by the decode() function
        // - if a message we find a well formed message, cut-off the expected_length
        // - if the message is not well formed (correct prefix by accident), cut-off 1 char only
        this.buf = this.buf.slice(this.expected_length);
        this.expected_length = 6;

        // w.info("Attempting to parse packet, message candidate buffer is ["+mbuf.toByteArray()+"]");

        try {
            m = this.decode(mbuf);
            this.total_packets_received += 1;
        }
        catch(e) {
            // Set buffer in question and re-throw to generic error handling
            this.bufInError = mbuf;
            throw e;
        }
    }

    return m;

}

// input some data bytes, possibly returning an array of new messages
MAVLink.prototype.parseBuffer = function(s) {

    // Get a message, if one is available in the stream.
    var m = this.parseChar(s);

    // No messages available, bail.
    if ( null === m ) {
        return null;
    }

    // While more valid messages can be read from the existing buffer, add
    // them to the array of new messages and return them.
    var ret = [m];
    while(true) {
        m = this.parseChar();
        if ( null === m ) {
            // No more messages left.
            return ret;
        }
        ret.push(m);
    }
    return ret;

}

/* decode a buffer as a MAVLink message */
MAVLink.prototype.decode = function(msgbuf) {

    var magic, mlen, seq, srcSystem, srcComponent, unpacked, msgId;

    // decode the header
    try {
        unpacked = jspack.Unpack('cBBBBB', msgbuf.slice(0, 6));
        magic = unpacked[0];
        mlen = unpacked[1];
        seq = unpacked[2];
        srcSystem = unpacked[3];
        srcComponent = unpacked[4];
        msgId = unpacked[5];
    }
    catch(e) {
        throw new Error('Unable to unpack MAVLink header: ' + e.message);
    }

    if (magic.charCodeAt(0) != 254) {
        throw new Error("Invalid MAVLink prefix ("+magic.charCodeAt(0)+")");
    }

    if( mlen != msgbuf.length - 8 ) {
        throw new Error("Invalid MAVLink message length.  Got " + (msgbuf.length - 8) + " expected " + mlen + ", msgId=" + msgId);
    }

    if( false === _.has(mavlink.map, msgId) ) {
        throw new Error("Unknown MAVLink message ID (" + msgId + ")");
    }

    // decode the payload
    // refs: (fmt, type, order_map, crc_extra) = mavlink.map[msgId]
    var decoder = mavlink.map[msgId];

    // decode the checksum
    try {
        var receivedChecksum = jspack.Unpack('<H', msgbuf.slice(msgbuf.length - 2));
    } catch (e) {
        throw new Error("Unable to unpack MAVLink CRC: " + e.message);
    }

    var messageChecksum = mavlink.x25Crc(msgbuf.slice(1, msgbuf.length - 2));

    // Assuming using crc_extra = True.  See the message.prototype.pack() function.
    messageChecksum = mavlink.x25Crc([decoder.crc_extra], messageChecksum);

    if ( receivedChecksum != messageChecksum ) {
        throw new Error('invalid MAVLink CRC in msgID ' +msgId+ ', got 0x' + receivedChecksum + ' checksum, calculated payload checkum as 0x'+messageChecksum );
    }

    // Decode the payload and reorder the fields to match the order map.
    try {
        var t = jspack.Unpack(decoder.format, msgbuf.slice(6, msgbuf.length));
    }
    catch (e) {
        throw new Error('Unable to unpack MAVLink payload type='+decoder.type+' format='+decoder.format+' payloadLength='+ msgbuf.slice(6, -2).length +': '+ e.message);
    }

    // Reorder the fields to match the order map
    var args = [];
    _.each(t, function(e, i, l) {
        args[i] = t[decoder.order_map[i]]
    });

    // construct the message object
    try {
        var m = new decoder.type(args);
        m.set.call(m, args);
    }
    catch (e) {
        throw new Error('Unable to instantiate MAVLink message of type '+decoder.type+' : ' + e.message);
    }
    m.msgbuf = msgbuf;
    m.payload = msgbuf.slice(6);
    m.crc = receivedChecksum;
    m.header = new mavlink.header(msgId, mlen, seq, srcSystem, srcComponent);
    this.log(m);
    return m;
}

""", xml)


def generate_footer(outf):
    t.write(outf, """

// Expose this code as a module
module.exports = mavlink;

""")


def generate(basename, xml):
    '''generate complete javascript implementation'''

    if basename.rfind(os.sep) >= 0:
        jspackFilename = basename[0:basename.rfind(os.sep)] + '/jspack.js'
    else:
        jspackFilename = 'jspack.js'

    if basename.endswith('.js'):
        filename = basename
    else:
        filename = basename + '.js'

    msgs = []
    enums = []
    filelist = []
    for x in xml:
        msgs.extend(x.message)
        enums.extend(x.enum)
        filelist.append(os.path.basename(x.filename))

    for m in msgs:
        if xml[0].little_endian:
            m.fmtstr = '<'
        else:
            m.fmtstr = '>'
        for f in m.ordered_fields:
            m.fmtstr += mavfmt(f)
        m.order_map = [0] * len(m.fieldnames)
        for i in range(0, len(m.fieldnames)):
            m.order_map[i] = m.ordered_fieldnames.index(m.fieldnames[i])

    print(("Generating %s" % filename))
    outf = open(filename, "w")
    generate_preamble(outf, msgs, filelist, xml[0])
    generate_enums(outf, enums)
    generate_message_ids(outf, msgs)
    generate_classes(outf, msgs)
    generate_mavlink_class(outf, msgs, xml[0])
    generate_footer(outf)
    outf.close()
    print(("Generated %s OK" % filename))
    copyfile('./javascript/lib/jspack/jspack.js', jspackFilename)
    print(("Copied jspack %s" % jspackFilename))
