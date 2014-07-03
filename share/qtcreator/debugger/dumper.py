############################################################################
#
# Copyright (C) 2014 Digia Plc and/or its subsidiary(-ies).
# Contact: http://www.qt-project.org/legal
#
# This file is part of Qt Creator.
#
# Commercial License Usage
# Licensees holding valid commercial Qt licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Digia.  For licensing terms and
# conditions see http://qt.digia.com/licensing.  For further information
# use the contact form at http://qt.digia.com/contact-us.
#
# GNU Lesser General Public License Usage
# Alternatively, this file may be used under the terms of the GNU Lesser
# General Public License version 2.1 as published by the Free Software
# Foundation and appearing in the file LICENSE.LGPL included in the
# packaging of this file.  Please review the following information to
# ensure the GNU Lesser General Public License version 2.1 requirements
# will be met: http://www.gnu.org/licenses/old-licenses/lgpl-2.1.html.
#
# In addition, as a special exception, Digia gives you certain additional
# rights.  These rights are described in the Digia Qt LGPL Exception
# version 1.1, included in the file LGPL_EXCEPTION.txt in this package.
#
############################################################################

import os
import struct
import sys
import base64
import re

if sys.version_info[0] >= 3:
    xrange = range
    toInteger = int
else:
    toInteger = long


verbosity = 0
verbosity = 1

# Debugger start modes. Keep in sync with DebuggerStartMode in debuggerconstants.h
NoStartMode, \
StartInternal, \
StartExternal,  \
AttachExternal,  \
AttachCrashedExternal,  \
AttachCore, \
AttachToRemoteServer, \
AttachToRemoteProcess, \
LoadRemoteCore, \
StartRemoteProcess, \
StartRemoteGdb,  \
StartRemoteEngine \
    = range(0, 12)


# Known special formats. Keep in sync with DisplayFormat in watchhandler.h
KnownDumperFormatBase, \
Latin1StringFormat, \
Utf8StringFormat, \
Local8BitStringFormat, \
Utf16StringFormat, \
Ucs4StringFormat, \
Array10Format, \
Array100Format, \
Array1000Format, \
Array10000Format, \
SeparateLatin1StringFormat, \
SeparateUtf8StringFormat \
    = range(100, 112)

def hasPlot():
    fileName = "/usr/bin/gnuplot"
    return os.path.isfile(fileName) and os.access(fileName, os.X_OK)

try:
    import subprocess
    def arrayForms():
        if hasPlot():
            return "Normal,Plot"
        return "Normal"
except:
    def arrayForms():
        return "Normal"


class ReportItem:
    """
    Helper structure to keep temporary "best" information about a value
    or a type scheduled to be reported. This might get overridden be
    subsequent better guesses during a putItem() run.
    """
    def __init__(self, value = None, encoding = None, priority = -100, elided = None):
        self.value = value
        self.priority = priority
        self.encoding = encoding
        self.elided = elided

    def __str__(self):
        return "Item(value: %s, encoding: %s, priority: %s, elided: %s)" \
            % (self.value, self.encoding, self.priority, self.elided)


class Blob(object):
    """
    Helper structure to keep a blob of bytes, possibly
    in the inferior.
    """

    def __init__(self, data, isComplete = True):
        self.data = data
        self.size = len(data)
        self.isComplete = isComplete

    def size(self):
        return self.size

    def toBytes(self):
        """Retrieves "lazy" contents from memoryviews."""
        data = self.data

        major = sys.version_info[0]
        if major == 3 or (major == 2 and sys.version_info[1] >= 7):
            if isinstance(data, memoryview):
                data = data.tobytes()
        if major == 2 and isinstance(data, buffer):
            data = ''.join([c for c in data])
        return data

    def toString(self):
        data = self.toBytes()
        return data if sys.version_info[0] == 2 else data.decode("utf8")

    def extractByte(self, offset = 0):
        return struct.unpack_from("b", self.data, offset)[0]

    def extractShort(self, offset = 0):
        return struct.unpack_from("h", self.data, offset)[0]

    def extractUShort(self, offset = 0):
        return struct.unpack_from("H", self.data, offset)[0]

    def extractInt(self, offset = 0):
        return struct.unpack_from("i", self.data, offset)[0]

    def extractUInt(self, offset = 0):
        return struct.unpack_from("I", self.data, offset)[0]

    def extractLong(self, offset = 0):
        return struct.unpack_from("l", self.data, offset)[0]

    # FIXME: Note these should take target architecture into account.
    def extractULong(self, offset = 0):
        return struct.unpack_from("L", self.data, offset)[0]

    def extractInt64(self, offset = 0):
        return struct.unpack_from("q", self.data, offset)[0]

    def extractUInt64(self, offset = 0):
        return struct.unpack_from("Q", self.data, offset)[0]

    def extractDouble(self, offset = 0):
        return struct.unpack_from("d", self.data, offset)[0]

    def extractFloat(self, offset = 0):
        return struct.unpack_from("f", self.data, offset)[0]

#
# Gnuplot based display for array-like structures.
#
gnuplotPipe = {}
gnuplotPid = {}

def warn(message):
    print("XXX: %s\n" % message.encode("latin1"))


def showException(msg, exType, exValue, exTraceback):
    warn("**** CAUGHT EXCEPTION: %s ****" % msg)
    try:
        import traceback
        for line in traceback.format_exception(exType, exValue, exTraceback):
            warn("%s" % line)
    except:
        pass


def stripClassTag(typeName):
    if typeName.startswith("class "):
        return typeName[6:]
    if typeName.startswith("struct "):
        return typeName[7:]
    if typeName.startswith("const "):
        return typeName[6:]
    if typeName.startswith("volatile "):
        return typeName[9:]
    return typeName


class Children:
    def __init__(self, d, numChild = 1, childType = None, childNumChild = None,
            maxNumChild = None, addrBase = None, addrStep = None):
        self.d = d
        self.numChild = numChild
        self.childNumChild = childNumChild
        self.maxNumChild = maxNumChild
        self.addrBase = addrBase
        self.addrStep = addrStep
        self.printsAddress = True
        if childType is None:
            self.childType = None
        else:
            self.childType = stripClassTag(str(childType))
            if not self.d.isCli:
                self.d.put('childtype="%s",' % self.childType)
            if childNumChild is None:
                pass
                #if self.d.isSimpleType(childType):
                #    self.d.put('childnumchild="0",')
                #    self.childNumChild = 0
                #elif childType.code == PointerCode:
                #    self.d.put('childnumchild="1",')
                #    self.childNumChild = 1
            else:
                self.d.put('childnumchild="%s",' % childNumChild)
                self.childNumChild = childNumChild
        self.printsAddress = not self.d.putAddressRange(addrBase, addrStep)

    def __enter__(self):
        self.savedChildType = self.d.currentChildType
        self.savedChildNumChild = self.d.currentChildNumChild
        self.savedNumChild = self.d.currentNumChild
        self.savedMaxNumChild = self.d.currentMaxNumChild
        self.savedPrintsAddress = self.d.currentPrintsAddress
        self.d.currentChildType = self.childType
        self.d.currentChildNumChild = self.childNumChild
        self.d.currentNumChild = self.numChild
        self.d.currentMaxNumChild = self.maxNumChild
        self.d.currentPrintsAddress = self.printsAddress
        self.d.put(self.d.childrenPrefix)

    def __exit__(self, exType, exValue, exTraceBack):
        if not exType is None:
            if self.d.passExceptions:
                showException("CHILDREN", exType, exValue, exTraceBack)
            self.d.putNumChild(0)
            self.d.putValue("<not accessible>")
        if not self.d.currentMaxNumChild is None:
            if self.d.currentMaxNumChild < self.d.currentNumChild:
                self.d.put('{name="<incomplete>",value="",type="",numchild="0"},')
        self.d.currentChildType = self.savedChildType
        self.d.currentChildNumChild = self.savedChildNumChild
        self.d.currentNumChild = self.savedNumChild
        self.d.currentMaxNumChild = self.savedMaxNumChild
        self.d.currentPrintsAddress = self.savedPrintsAddress
        self.d.putNewline()
        self.d.put(self.d.childrenSuffix)
        return True

class PairedChildrenData:
    def __init__(self, d, pairType, keyType, valueType, useKeyAndValue):
        self.useKeyAndValue = useKeyAndValue
        self.pairType = pairType
        self.keyType = keyType
        self.valueType = valueType
        self.isCompact = d.isMapCompact(self.keyType, self.valueType)
        self.childType = valueType if self.isCompact else pairType
        ns = d.qtNamespace()
        self.keyIsQString = str(self.keyType) == ns + "QString"
        self.keyIsQByteArray = str(self.keyType) == ns + "QByteArray"

class PairedChildren(Children):
    def __init__(self, d, numChild, useKeyAndValue = False,
            pairType = None, keyType = None, valueType = None, maxNumChild = None):
        self.d = d
        if keyType is None:
            keyType = d.templateArgument(pairType, 0).unqualified()
        if valueType is None:
            valueType = d.templateArgument(pairType, 1)
        d.pairData = PairedChildrenData(d, pairType, keyType, valueType, useKeyAndValue)

        Children.__init__(self, d, numChild,
            d.pairData.childType,
            maxNumChild = maxNumChild,
            addrBase = None, addrStep = None)

    def __enter__(self):
        self.savedPairData = self.d.pairData if hasattr(self.d, "pairData") else None
        Children.__enter__(self)

    def __exit__(self, exType, exValue, exTraceBack):
        Children.__exit__(self, exType, exValue, exTraceBack)
        self.d.pairData = self.savedPairData if self.savedPairData else None


class SubItem:
    def __init__(self, d, component):
        self.d = d
        self.name = component
        self.iname = None

    def __enter__(self):
        self.d.enterSubItem(self)

    def __exit__(self, exType, exValue, exTraceBack):
        return self.d.exitSubItem(self, exType, exValue, exTraceBack)

class NoAddress:
    def __init__(self, d):
        self.d = d

    def __enter__(self):
        self.savedPrintsAddress = self.d.currentPrintsAddress
        self.d.currentPrintsAddress = False

    def __exit__(self, exType, exValue, exTraceBack):
        self.d.currentPrintsAddress = self.savedPrintsAddress

class TopLevelItem(SubItem):
    def __init__(self, d, iname):
        self.d = d
        self.iname = iname
        self.name = None

class UnnamedSubItem(SubItem):
    def __init__(self, d, component):
        self.d = d
        self.iname = "%s.%s" % (self.d.currentIName, component)
        self.name = None

class DumperBase:
    def __init__(self):
        self.isCdb = False
        self.isGdb = False
        self.isLldb = False
        self.isCli = False

        # Later set, or not set:
        # cachedQtVersion
        self.stringCutOff = 10000
        self.displayStringLimit = 100

        # This is a cache mapping from 'type name' to 'display alternatives'.
        self.qqFormats = {}

        # This is a cache of all known dumpers.
        self.qqDumpers = {}

        # This is a cache of all dumpers that support writing.
        self.qqEditable = {}

        # This keeps canonical forms of the typenames, without array indices etc.
        self.cachedFormats = {}

        # Maps type names to static metaobjects. If a type is known
        # to not be QObject derived, it contains a 0 value.
        self.knownStaticMetaObjects = {}

        self.childrenPrefix = 'children=['
        self.childrenSuffix = '],'

    def putNewline(self):
        pass

    def stripForFormat(self, typeName):
        if typeName in self.cachedFormats:
            return self.cachedFormats[typeName]
        stripped = ""
        inArray = 0
        for c in stripClassTag(typeName):
            if c == '<':
                break
            if c == ' ':
                continue
            if c == '[':
                inArray += 1
            elif c == ']':
                inArray -= 1
            if inArray and ord(c) >= 48 and ord(c) <= 57:
                continue
            stripped +=  c
        self.cachedFormats[typeName] = stripped
        return stripped

    # Hex decoding operating on str, return str.
    def hexdecode(self, s):
        if sys.version_info[0] == 2:
            return s.decode("hex")
        return bytes.fromhex(s).decode("utf8")

    # Hex decoding operating on str or bytes, return str.
    def hexencode(self, s):
        if sys.version_info[0] == 2:
            return s.encode("hex")
        if isinstance(s, str):
            s = s.encode("utf8")
        return base64.b16encode(s).decode("utf8")

    #def toBlob(self, value):
    #    """Abstract"""

    def is32bit(self):
        return self.ptrSize() == 4

    def is64bit(self):
        return self.ptrSize() == 8

    def isQt3Support(self):
        # assume no Qt 3 support by default
        return False

    # Clamps size to limit.
    def computeLimit(self, size, limit):
        if limit == 0:
            limit = self.displayStringLimit
        if limit is None or size <= limit:
            return 0, size
        return size, limit

    def vectorDataHelper(self, addr):
        if self.qtVersion() >= 0x050000:
            size = self.extractInt(addr + 4)
            alloc = self.extractInt(addr + 8) & 0x7ffffff
            data = addr + self.extractPointer(addr + 8 + self.ptrSize())
        else:
            alloc = self.extractInt(addr + 4)
            size = self.extractInt(addr + 8)
            data = addr + 16
        return data, size, alloc

    def byteArrayDataHelper(self, addr):
        if self.qtVersion() >= 0x050000:
            # QTypedArray:
            # - QtPrivate::RefCount ref
            # - int size
            # - uint alloc : 31, capacityReserved : 1
            # - qptrdiff offset
            size = self.extractInt(addr + 4)
            alloc = self.extractInt(addr + 8) & 0x7ffffff
            data = addr + self.extractPointer(addr + 8 + self.ptrSize())
            if self.ptrSize() == 4:
                data = data & 0xffffffff
            else:
                data = data & 0xffffffffffffffff
        else:
            # Data:
            # - QBasicAtomicInt ref;
            # - int alloc, size;
            # - [padding]
            # - char *data;
            alloc = self.extractInt(addr + 4)
            size = self.extractInt(addr + 8)
            data = self.extractPointer(addr + 8 + self.ptrSize())
        return data, size, alloc

    # addr is the begin of a QByteArrayData structure
    def encodeStringHelper(self, addr, limit):
        # Should not happen, but we get it with LLDB as result
        # of inferior calls
        if addr == 0:
            return 0, ""
        data, size, alloc = self.byteArrayDataHelper(addr)
        if alloc != 0:
            self.check(0 <= size and size <= alloc and alloc <= 100*1000*1000)
        elided, shown = self.computeLimit(size, limit)
        return elided, self.readMemory(data, 2 * shown)

    def encodeByteArrayHelper(self, addr, limit):
        data, size, alloc = self.byteArrayDataHelper(addr)
        if alloc != 0:
            self.check(0 <= size and size <= alloc and alloc <= 100*1000*1000)
        elided, shown = self.computeLimit(size, limit)
        return elided, self.readMemory(data, shown)

    def readMemory(self, addr, size):
        data = self.extractBlob(addr, size).toBytes()
        return self.hexencode(data)

    def encodeByteArray(self, value, limit = 0):
        elided, data = self.encodeByteArrayHelper(self.extractPointer(value), limit)
        return data

    def byteArrayData(self, value):
        return self.byteArrayDataHelper(self.extractPointer(value))

    def putByteArrayValueByAddress(self, addr):
        elided, data = self.encodeByteArrayHelper(addr, self.displayStringLimit)
        self.putValue(data, Hex2EncodedLatin1, elided=elided)

    def putByteArrayValue(self, value):
        elided, data = self.encodeByteArrayHelper(self.extractPointer(value), self.displayStringLimit)
        self.putValue(data, Hex2EncodedLatin1, elided=elided)

    def encodeString(self, value, limit = 0):
        elided, data = self.encodeStringHelper(self.extractPointer(value), limit)
        return data

    def stringData(self, value):
        return self.byteArrayDataHelper(self.extractPointer(value))

    def extractTemplateArgument(self, typename, position):
        level = 0
        skipSpace = False
        inner = ''
        for c in typename[typename.find('<') + 1 : -1]:
            if c == '<':
                inner += c
                level += 1
            elif c == '>':
                level -= 1
                inner += c
            elif c == ',':
                if level == 0:
                    if position == 0:
                        return inner.strip()
                    position -= 1
                    inner = ''
                else:
                    inner += c
                    skipSpace = True
            else:
                if skipSpace and c == ' ':
                    pass
                else:
                    inner += c
                    skipSpace = False
        return inner.strip()

    def putStringValueByAddress(self, addr):
        elided, data = self.encodeStringHelper(addr, self.displayStringLimit)
        self.putValue(data, Hex4EncodedLittleEndian, elided=elided)

    def putStringValue(self, value):
        elided, data = self.encodeStringHelper(self.extractPointer(value), self.displayStringLimit)
        self.putValue(data, Hex4EncodedLittleEndian, elided=elided)

    def putAddressItem(self, name, value, type = ""):
        with SubItem(self, name):
            self.putValue("0x%x" % value)
            self.putType(type)
            self.putNumChild(0)

    def putIntItem(self, name, value):
        with SubItem(self, name):
            self.putValue(value)
            self.putType("int")
            self.putNumChild(0)

    def putBoolItem(self, name, value):
        with SubItem(self, name):
            self.putValue(value)
            self.putType("bool")
            self.putNumChild(0)

    def putGenericItem(self, name, type, value, encoding = None):
        with SubItem(self, name):
            self.putValue(value, encoding)
            self.putType(type)
            self.putNumChild(0)

    def putCallItem(self, name, value, func, *args):
        try:
            result = self.callHelper(value, func, args)
            with SubItem(self, name):
                self.putItem(result)
        except:
            with SubItem(self, name):
                self.putValue("<not callable>")
                self.putNumChild(0)

    def call(self, value, func, *args):
        return self.callHelper(value, func, args)

    def putAddressRange(self, base, step):
        try:
            if not addrBase is None and not step is None:
                self.put('addrbase="0x%x",' % toInteger(base))
                self.put('addrstep="0x%x",' % toInteger(step))
                return True
        except:
            #warn("ADDRBASE: %s" % base)
            #warn("ADDRSTEP: %s" % step)
            pass
        return False

        #warn("CHILDREN: %s %s %s" % (numChild, childType, childNumChild))
    def putMapName(self, value, index = -1):
        ns = self.qtNamespace()
        if str(value.type) == ns + "QString":
            self.put('key="%s",' % self.encodeString(value))
            self.put('keyencoded="%s",' % Hex4EncodedLittleEndian)
        elif str(value.type) == ns + "QByteArray":
            self.put('key="%s",' % self.encodeByteArray(value))
            self.put('keyencoded="%s",' % Hex2EncodedLatin1)
        else:
            val = str(value.GetValue()) if self.isLldb else str(value)
            if index == -1:
                key = 'key="%s",' % val
            else:
                key = 'key="[%d] %s",' % (index, val)
            self.put('key="%s",' % self.hexencode(key))
            self.put('keyencoded="%s",' % Hex2EncodedLatin1)

    def putPair(self, pair, index = -1):
        if self.pairData.useKeyAndValue:
            key = pair["key"]
            value = pair["value"]
        else:
            key = pair["first"]
            value = pair["second"]
        if self.pairData.isCompact:
            if self.pairData.keyIsQString:
                self.put('key="%s",' % self.encodeString(key))
                self.put('keyencoded="%s",' % Hex4EncodedLittleEndian)
            elif self.pairData.keyIsQByteArray:
                self.put('key="%s",' % self.encodeByteArray(key))
                self.put('keyencoded="%s",' % Hex2EncodedLatin1)
            else:
                name = str(key.GetValue()) if self.isLldb else str(key)
                if index == -1:
                    self.put('name="%s",' % name)
                else:
                    self.put('key="[%d] %s",' % (index, name))
            self.putItem(value)
        else:
            self.putEmptyValue()
            self.putNumChild(2)
            self.putField("iname", self.currentIName)
            if self.isExpanded():
                with Children(self):
                    if self.pairData.useKeyAndValue:
                        self.putSubItem("key", key)
                        self.putSubItem("value", value)
                    else:
                        self.putSubItem("first", key)
                        self.putSubItem("second", value)

    def putPlainChildren(self, value, dumpBase = True):
        self.putEmptyValue(-99)
        self.putNumChild(1)
        if self.isExpanded():
            with Children(self):
                self.putFields(value, dumpBase)

    def isMapCompact(self, keyType, valueType):
        format = self.currentItemFormat()
        if format == 2:
            return True # Compact.
        return self.isSimpleType(keyType) and self.isSimpleType(valueType)


    def check(self, exp):
        if not exp:
            raise RuntimeError("Check failed")

    def checkRef(self, ref):
        try:
            count = int(ref["atomic"]["_q_value"]) # Qt 5.
            minimum = -1
        except:
            count = int(ref["_q_value"]) # Qt 4.
            minimum = 0
        # Assume there aren't a million references to any object.
        self.check(count >= minimum)
        self.check(count < 1000000)

    def findFirstZero(self, p, maximum):
        for i in xrange(maximum):
            if int(p.dereference()) == 0:
                return 0, i
            p = p + 1
        # Real end is unknown.
        return -1, maximum

    def encodeCArray(self, p, innerType, limit):
        t = self.lookupType(innerType)
        p = p.cast(t.pointer())
        elided, shown = self.findFirstZero(p, limit)
        return elided, self.readMemory(p, shown * t.sizeof)

    def putItemCount(self, count, maximum = 1000000000):
        # This needs to override the default value, so don't use 'put' directly.
        if count > maximum:
            self.putValue('<>%s items>' % maximum)
        else:
            self.putValue('<%s items>' % count)
        self.putNumChild(count)

    def putField(self, name, value):
        self.put('%s="%s",' % (name, value))

    def putType(self, type, priority = 0):
        # Higher priority values override lower ones.
        if priority >= self.currentType.priority:
            self.currentType.value = str(type)
            self.currentType.priority = priority

    def putValue(self, value, encoding = None, priority = 0, elided = None):
        # Higher priority values override lower ones.
        # elided = 0 indicates all data is available in value,
        # otherwise it's the true length.
        if priority >= self.currentValue.priority:
            self.currentValue = ReportItem(value, encoding, priority, elided)

    def putEmptyValue(self, priority = -10):
        if priority >= self.currentValue.priority:
            self.currentValue = ReportItem("", None, priority, None)

    def putName(self, name):
        self.put('name="%s",' % name)

    def putBetterType(self, type):
        if isinstance(type, ReportItem):
            self.currentType.value = str(type.value)
        else:
            self.currentType.value = str(type)
        self.currentType.priority += 1

    def putNoType(self):
        # FIXME: replace with something that does not need special handling
        # in SubItem.__exit__().
        self.putBetterType(" ")

    def putInaccessible(self):
        #self.putBetterType(" ")
        self.putNumChild(0)
        self.currentValue.value = None

    def putNamedSubItem(self, component, value, name):
        with SubItem(self, component):
            self.putName(name)
            self.putItem(value)

    def isExpanded(self):
        #warn("IS EXPANDED: %s in %s: %s" % (self.currentIName,
        #    self.expandedINames, self.currentIName in self.expandedINames))
        return self.currentIName in self.expandedINames

    def putPlainChildren(self, value):
        self.putEmptyValue(-99)
        self.putNumChild(1)
        if self.currentIName in self.expandedINames:
            with Children(self):
               self.putFields(value)

    def putCStyleArray(self, value):
        type = value.type.unqualified()
        innerType = value[0].type
        #self.putAddress(value.address)
        self.putType(type)
        self.putNumChild(1)
        format = self.currentItemFormat()
        isDefault1 = format == None and str(innerType.unqualified()) == "char"
        isDefault2 = format == None and str(innerType.unqualified()) == "wchar_t"
        if isDefault1 or isDefault2 or format == 0 or format == 1 or format == 2:
            blob = self.readMemory(self.addressOf(value), type.sizeof)

        if isDefault1:
            # Use Latin1 as default for char [].
            self.putValue(blob, Hex2EncodedLatin1)
        elif isDefault2:
            if type.sizeof == 2:
                self.putValue(blob, Hex4EncodedLittleEndian)
            else:
                self.putValue(blob, Hex8EncodedLittleEndian)
        elif format == 0:
            # Explicitly requested Latin1 formatting.
            self.putValue(blob, Hex2EncodedLatin1)
        elif format == 1:
            # Explicitly requested UTF-8 formatting.
            self.putValue(blob, Hex2EncodedUtf8)
        elif format == 2:
            # Explicitly requested Local 8-bit formatting.
            self.putValue(blob, Hex2EncodedLocal8Bit)
        else:
            try:
                self.putValue("@0x%x" % self.pointerValue(value.cast(innerType.pointer())))
            except:
                self.putEmptyValue()

        if self.currentIName in self.expandedINames:
            try:
                # May fail on artificial items like xmm register data.
                p = self.addressOf(value)
                ts = innerType.sizeof
                if not self.tryPutArrayContents(p, int(type.sizeof / ts), innerType):
                    with Children(self, childType=innerType,
                            addrBase=p, addrStep=ts):
                        self.putFields(value)
            except:
                with Children(self, childType=innerType):
                    self.putFields(value)

    def cleanAddress(self, addr):
        if addr is None:
            return "<no address>"
        # We cannot use str(addr) as it yields rubbish for char pointers
        # that might trigger Unicode encoding errors.
        #return addr.cast(lookupType("void").pointer())
        # We do not use "hex(...)" as it (sometimes?) adds a "L" suffix.
        try:
            return "0x%x" % toInteger(addr)
        except:
            warn("CANNOT CONVERT TYPE: %s" % type(addr))
            return str(addr)

    def tryPutArrayContents(self, base, n, innerType):
        enc = self.simpleEncoding(innerType)
        if not enc:
            return False
        size = n * innerType.sizeof;
        self.put('childtype="%s",' % innerType)
        self.put('addrbase="0x%x",' % toInteger(base))
        self.put('addrstep="0x%x",' % toInteger(innerType.sizeof))
        self.put('arrayencoding="%s",' % enc)
        self.put('arraydata="')
        self.put(self.readMemory(base, size))
        self.put('",')
        return True

    def putDisplay(self, format, value = None, cmd = None):
        self.put('editformat="%s",' % format)
        if cmd is None:
            if not value is None:
                self.put('editvalue="%s",' % value)
        else:
            self.put('editvalue="%s|%s",' % (cmd, value))

    def putFormattedPointer(self, value):
        #warn("POINTER: %s" % value)
        if self.isNull(value):
            #warn("NULL POINTER")
            self.putType(value.type)
            self.putValue("0x0")
            self.putNumChild(0)
            return

        typeName = str(value.type)
        innerType = value.type.target().unqualified()
        innerTypeName = str(innerType)

        try:
            value.dereference()
        except:
            # Failure to dereference a pointer should at least
            # show the value of a pointer.
            self.putValue(self.cleanAddress(value))
            self.putType(typeName)
            self.putNumChild(0)
            return

        format = self.currentItemFormat(value.type)

        if innerTypeName == "void":
            #warn("VOID POINTER: %s" % format)
            self.putType(typeName)
            self.putValue(str(value))
            self.putNumChild(0)
            return

        if format == None and innerTypeName == "char":
            # Use Latin1 as default for char *.
            self.putType(typeName)
            (elided, data) = self.encodeCArray(value, "unsigned char", self.displayStringLimit)
            self.putValue(data, Hex2EncodedLatin1, elided=elided)
            self.putNumChild(0)
            return

        if format == 0:
            # Explicitly requested bald pointer.
            self.putType(typeName)
            self.putValue(self.hexencode(str(value)), Hex2EncodedUtf8WithoutQuotes)
            self.putNumChild(1)
            if self.currentIName in self.expandedINames:
                with Children(self):
                    with SubItem(self, '*'):
                        self.putItem(value.dereference())
            return

        if format == Latin1StringFormat or format == SeparateLatin1StringFormat:
            # Explicitly requested Latin1 formatting.
            limit = self.displayStringLimit if format == Latin1StringFormat else 1000000
            self.putType(typeName)
            (elided, data) = self.encodeCArray(value, "unsigned char", limit)
            self.putValue(data, Hex2EncodedLatin1, elided=elided)
            self.putNumChild(0)
            self.putDisplay((StopDisplay if format == Latin1StringFormat else DisplayLatin1String), data)
            return

        if format == Utf8StringFormat or format == SeparateUtf8StringFormat:
            # Explicitly requested UTF-8 formatting.
            limit = self.displayStringLimit if format == Utf8StringFormat else 1000000
            self.putType(typeName)
            (elided, data) = self.encodeCArray(value, "unsigned char", limit)
            self.putValue(data, Hex2EncodedUtf8, elided=elided)
            self.putNumChild(0)
            self.putDisplay((StopDisplay if format == Utf8StringFormat else DisplayUtf8String), data)
            return

        if format == Local8BitStringFormat:
            # Explicitly requested local 8 bit formatting.
            self.putType(typeName)
            (elided, data) = self.encodeCArray(value, "unsigned char", self.displayStringLimit)
            self.putValue(data, Hex2EncodedLocal8Bit, elided=elided)
            self.putNumChild(0)
            return

        if format == Utf16StringFormat:
            # Explicitly requested UTF-16 formatting.
            self.putType(typeName)
            (elided, data) = self.encodeCArray(value, "unsigned short", self.displayStringLimit)
            self.putValue(data, Hex4EncodedLittleEndian, elided=elided)
            self.putNumChild(0)
            return

        if format == Ucs4StringFormat:
            # Explicitly requested UCS-4 formatting.
            self.putType(typeName)
            (elided, data) = self.encodeCArray(value, "unsigned int", self.displayStringLimit)
            self.putValue(data, Hex8EncodedLittleEndian, elided=elided)
            self.putNumChild(0)
            return

        if not format is None \
            and format >= Array10Format and format <= Array1000Format:
            # Explicitly requested formatting as array of n items.
            n = (10, 100, 1000, 10000)[format - Array10Format]
            self.putType(typeName)
            self.putItemCount(n)
            self.putArrayData(value, n, innerType)
            return

        if self.isFunctionType(innerType):
            # A function pointer.
            val = str(value)
            pos = val.find(" = ") # LLDB only, but...
            if pos > 0:
                val = val[pos + 3:]
            self.putValue(val)
            self.putType(innerTypeName)
            self.putNumChild(0)
            return

        #warn("AUTODEREF: %s" % self.autoDerefPointers)
        #warn("INAME: %s" % self.currentIName)
        if self.autoDerefPointers or self.currentIName.endswith('.this'):
            ## Generic pointer type with format None
            #warn("GENERIC AUTODEREF POINTER: %s AT %s TO %s"
            #    % (type, value.address, innerTypeName))
            # Never dereference char types.
            if innerTypeName != "char" \
                    and innerTypeName != "signed char" \
                    and innerTypeName != "unsigned char"  \
                    and innerTypeName != "wchar_t":
                self.putType(innerTypeName)
                savedCurrentChildType = self.currentChildType
                self.currentChildType = stripClassTag(innerTypeName)
                self.putItem(value.dereference())
                self.currentChildType = savedCurrentChildType
                #self.putPointerValue(value)
                self.putOriginalAddress(value)
                return

        #warn("GENERIC PLAIN POINTER: %s" % value.type)
        #warn("ADDR PLAIN POINTER: 0x%x" % value.address)
        self.putType(typeName)
        self.putValue("0x%x" % self.pointerValue(value))
        self.putNumChild(1)
        if self.currentIName in self.expandedINames:
            with Children(self):
                with SubItem(self, "*"):
                    self.putItem(value.dereference())

    def putOriginalAddress(self, value):
        if not value.address is None:
            self.put('origaddr="0x%x",' % toInteger(value.address))

    def putQObjectNameValue(self, value):
        try:
            intSize = self.intSize()
            ptrSize = self.ptrSize()
            # dd = value["d_ptr"]["d"] is just behind the vtable.
            dd = self.extractPointer(value, offset=ptrSize)

            if self.qtVersion() < 0x050000:
                # Size of QObjectData: 5 pointer + 2 int
                #  - vtable
                #   - QObject *q_ptr;
                #   - QObject *parent;
                #   - QObjectList children;
                #   - uint isWidget : 1; etc..
                #   - int postedEvents;
                #   - QMetaObject *metaObject;

                # Offset of objectName in QObjectPrivate: 5 pointer + 2 int
                #   - [QObjectData base]
                #   - QString objectName
                objectName = self.extractPointer(dd + 5 * ptrSize + 2 * intSize)

            else:
                # Size of QObjectData: 5 pointer + 2 int
                #   - vtable
                #   - QObject *q_ptr;
                #   - QObject *parent;
                #   - QObjectList children;
                #   - uint isWidget : 1; etc...
                #   - int postedEvents;
                #   - QDynamicMetaObjectData *metaObject;
                extra = self.extractPointer(dd + 5 * ptrSize + 2 * intSize)
                if extra == 0:
                    return False

                # Offset of objectName in ExtraData: 6 pointer
                #   - QVector<QObjectUserData *> userData; only #ifndef QT_NO_USERDATA
                #   - QList<QByteArray> propertyNames;
                #   - QList<QVariant> propertyValues;
                #   - QVector<int> runningTimers;
                #   - QList<QPointer<QObject> > eventFilters;
                #   - QString objectName
                objectName = self.extractPointer(extra + 5 * ptrSize)

            data, size, alloc = self.byteArrayDataHelper(objectName)

            # Object names are short, and GDB can crash on to big chunks.
            # Since this here is a convenience feature only, limit it.
            if size <= 0 or size > 80:
                return False

            raw = self.readMemory(data, 2 * size)
            self.putValue(raw, Hex4EncodedLittleEndian, 1)
            return True

        except:
        #    warn("NO QOBJECT: %s" % value.type)
            pass


    def extractStaticMetaObjectHelper(self, typeobj):
        """
        Checks whether type has a Q_OBJECT macro.
        Returns the staticMetaObject, or 0.
        """

        if self.isSimpleType(typeobj):
            return 0

        typeName = str(typeobj)
        isQObjectProper = typeName == self.qtNamespace() + "QObject"

        if not isQObjectProper:
            if self.directBaseClass(typeobj, 0) is None:
                return 0

            # No templates for now.
            if typeName.find('<') >= 0:
                return 0

        result = self.findStaticMetaObject(typeName)

        # We need to distinguish Q_OBJECT from Q_GADGET:
        # a Q_OBJECT SMO has a non-null superdata (unless it's QObject itself),
        # a Q_GADGET SMO has a null superdata (hopefully)
        if result and not isQObjectProper:
            superdata = self.extractPointer(result)
            if toInteger(superdata) == 0:
                # This looks like a Q_GADGET
                return 0

        return result

    def extractStaticMetaObject(self, typeobj):
        """
        Checks recursively whether a type derives from QObject.
        """
        if not self.useFancy:
            return 0

        typeName = str(typeobj)
        result = self.knownStaticMetaObjects.get(typeName, None)
        if result is not None: # Is 0 or the static metaobject.
            return result

        try:
            result = self.extractStaticMetaObjectHelper(typeobj)
        except RuntimeError as error:
            warn("METAOBJECT EXTRACTION FAILED: %s" % error)
            result = 0
        except:
            warn("METAOBJECT EXTRACTION FAILED FOR UNKNOWN REASON")
            result = 0

        if not result:
            base = self.directBaseClass(typeobj, 0)
            if base:
                result = self.extractStaticMetaObject(base)

        self.knownStaticMetaObjects[typeName] = result
        return result

    def staticQObjectMetaData(self, metaobject, offset1, offset2, step):
        items = []
        dd = metaobject["d"]
        data = self.extractPointer(dd["data"])
        sd = self.extractPointer(dd["stringdata"])

        metaObjectVersion = self.extractInt(data)
        itemCount = self.extractInt(data + offset1)
        itemData = -offset2 if offset2 < 0 else self.extractInt(data + offset2)

        if metaObjectVersion >= 7: # Qt 5.
            byteArrayDataType = self.lookupType(self.qtNamespace() + "QByteArrayData")
            byteArrayDataSize = byteArrayDataType.sizeof
            for i in range(itemCount):
                x = data + (itemData + step * i) * 4
                literal = sd + self.extractInt(x) * byteArrayDataSize
                ldata, lsize, lalloc = self.byteArrayDataHelper(literal)
                items.append(self.extractBlob(ldata, lsize).toString())
        else: # Qt 4.
            for i in range(itemCount):
                x = data + (itemData + step * i) * 4
                ldata = sd + self.extractInt(x)
                items.append(self.extractCString(ldata).decode("utf8"))

        return items

    def staticQObjectPropertyCount(self, metaobject):
        return self.extractInt(self.extractPointer(metaobject["d"]["data"]) + 24)

    def staticQObjectPropertyNames(self, metaobject):
        return self.staticQObjectMetaData(metaobject, 24, 28, 3)

    def staticQObjectMethodCount(self, metaobject):
        return self.extractInt(self.extractPointer(metaobject["d"]["data"]) + 16)

    def staticQObjectMethodNames(self, metaobject):
        return self.staticQObjectMetaData(metaobject, 16, 20, 5)

    def staticQObjectSignalCount(self, metaobject):
        return self.extractInt(self.extractPointer(metaobject["d"]["data"]) + 52)

    def staticQObjectSignalNames(self, metaobject):
        return self.staticQObjectMetaData(metaobject, 52, -14, 5)

    def extractCString(self, addr):
        result = bytearray()
        while True:
            d = self.extractByte(addr)
            if d == 0:
                break
            result.append(d)
            addr += 1
        return result

    def listChildrenGenerator(self, addr, typeName):
        innerType = self.lookupType(self.qtNamespace() + typeName)
        base = self.extractPointer(addr)
        begin = self.extractInt(base + 8)
        end = self.extractInt(base + 12)
        array = base + 16
        if self.qtVersion() < 0x50000:
            array += self.ptrSize()
        size = end - begin
        innerSize = innerType.sizeof
        stepSize = self.ptrSize()
        addr = array + begin * stepSize
        isInternal = innerSize <= stepSize and self.isMovableType(innerType)
        for i in range(size):
            if isInternal:
                yield self.createValue(addr + i * stepSize, innerType)
            else:
                p = self.extractPointer(addr + i * stepSize)
                yield self.createValue(p, innerType)


    # This is called is when a QObject derived class is expanded
    def putQObjectGuts(self, qobject, smo):
        intSize = self.intSize()
        ptrSize = self.ptrSize()
        # dd = value["d_ptr"]["d"] is just behind the vtable.
        dd = self.extractPointer(qobject, offset=ptrSize)
        isQt5 = self.qtVersion() >= 0x50000

        extraDataOffset = 5 * ptrSize + 8 if isQt5 else 6 * ptrSize + 8
        extraData = self.extractPointer(dd + extraDataOffset)
        #with SubItem(self, "[extradata]"):
        #    self.putValue("0x%x" % toInteger(extraData))

        # Parent and children.
        try:
            d_ptr = qobject["d_ptr"]["d"]
            self.putSubItem("[parent]", d_ptr["parent"])
            self.putSubItem("[children]", d_ptr["children"])
        except:
            pass

        with SubItem(self, "[properties]"):
            propertyCount = 0
            if self.isExpanded():
                propertyNames = self.staticQObjectPropertyNames(smo)
                propertyCount = len(propertyNames) # Doesn't include dynamic properties.
                with Children(self):
                    # Static properties.
                    for i in range(propertyCount):
                        name = propertyNames[i]
                        self.putCallItem(str(name), qobject, "property", '"' + name + '"')

                    # Dynamic properties.
                    if extraData:
                        names = self.listChildrenGenerator(extraData + ptrSize, "QByteArray")
                        values = self.listChildrenGenerator(extraData + 2 * ptrSize, "QVariant")
                        for (k, v) in zip(names, values):
                            with SubItem(self, propertyCount):
                                self.put('key="%s",' % self.encodeByteArray(k))
                                self.put('keyencoded="%s",' % Hex2EncodedLatin1)
                                self.putItem(v)
                                propertyCount += 1

            self.putValue(str('<%s items>' % propertyCount if propertyCount else '<>0 items>'))
            self.putNumChild(1)

        with SubItem(self, "[methods]"):
            methodCount = self.staticQObjectMethodCount(smo)
            self.putItemCount(methodCount)
            if self.isExpanded():
                methodNames = self.staticQObjectMethodNames(smo)
                with Children(self):
                    for i in range(methodCount):
                        k = methodNames[i]
                        with SubItem(self, k):
                            self.putEmptyValue()

        with SubItem(self, "[signals]"):
            signalCount = self.staticQObjectSignalCount(smo)
            self.putItemCount(signalCount)
            if self.isExpanded():
                signalNames = self.staticQObjectSignalNames(smo)
                signalCount = len(signalNames)
                with Children(self):
                    for i in range(signalCount):
                        k = signalNames[i]
                        with SubItem(self, k):
                            self.putEmptyValue()
                    self.putQObjectConnections(qobject)

    def putQObjectConnections(self, qobject):
        with SubItem(self, "[connections]"):
            ptrSize = self.ptrSize()
            self.putNoType()
            ns = self.qtNamespace()
            privateTypeName = ns + "QObjectPrivate"
            privateType = self.lookupType(privateTypeName)
            dd = qobject["d_ptr"]["d"]
            d_ptr = dd.cast(privateType.pointer()).dereference()
            connections = d_ptr["connectionLists"]
            if self.isNull(connections):
                self.putItemCount(0)
            else:
                connections = connections.dereference()
                connections = connections.cast(self.directBaseClass(connections.type))
                self.putValue('<>0 items>')
                self.putNumChild(1)
            if self.isExpanded():
                pp = 0
                with Children(self):
                    innerType = self.templateArgument(connections.type, 0)
                    # Should check:  innerType == ns::QObjectPrivate::ConnectionList
                    base = self.extractPointer(connections)
                    data, size, alloc = self.vectorDataHelper(base)
                    connectionType = self.lookupType(ns + "QObjectPrivate::Connection")
                    for i in xrange(size):
                        first = self.extractPointer(data + i * 2 * ptrSize)
                        while first:
                            self.putSubItem("%s" % pp,
                                self.createPointerValue(first, connectionType))
                            first = self.extractPointer(first + 3 * ptrSize)
                            # We need to enforce some upper limit.
                            pp += 1
                            if pp > 1000:
                                break

    def isKnownMovableType(self, typeName):
        if typeName in (
                "QBrush", "QBitArray", "QByteArray", "QCustomTypeInfo", "QChar", "QDate",
                "QDateTime", "QFileInfo", "QFixed", "QFixedPoint", "QFixedSize",
                "QHashDummyValue", "QIcon", "QImage", "QLine", "QLineF", "QLatin1Char",
                "QLocale", "QMatrix", "QModelIndex", "QPoint", "QPointF", "QPen",
                "QPersistentModelIndex", "QResourceRoot", "QRect", "QRectF", "QRegExp",
                "QSize", "QSizeF", "QString", "QTime", "QTextBlock", "QUrl", "QVariant",
                "QXmlStreamAttribute", "QXmlStreamNamespaceDeclaration",
                "QXmlStreamNotationDeclaration", "QXmlStreamEntityDeclaration"
                ):
            return True

        return typeName == "QStringList" and self.qtVersion() >= 0x050000

    def currentItemFormat(self, type = None):
        format = self.formats.get(self.currentIName)
        if format is None:
            if type is None:
                type = self.currentType.value
            needle = self.stripForFormat(str(type))
            format = self.typeformats.get(needle)
        return format

    def putArrayData(self, base, n, innerType = None,
            childNumChild = None, maxNumChild = 10000):
        if innerType is None:
            innerType = base.dereference().type
        if not self.tryPutArrayContents(base, n, innerType):
            base = self.createPointerValue(base, innerType)
            with Children(self, n, innerType, childNumChild, maxNumChild,
                    base, innerType.sizeof):
                for i in self.childRange():
                    i = toInteger(i)
                    self.putSubItem(i, (base + i).dereference())

    def putArrayItem(self, name, addr, n, typeName, plotFormat = 2):
        with SubItem(self, name):
            self.putEmptyValue()
            self.putType("%s [%d]" % (typeName, n))
            self.putArrayData(addr, n, self.lookupType(typeName))
            self.putAddress(addr)

    def putPlotData(self, base, n, typeobj, plotFormat = 2):
        if self.isExpanded():
            self.putArrayData(base, n, typeobj)
        if not hasPlot():
            return
        if not self.isSimpleType(typeobj):
            #self.putValue(self.currentValue.value + " (not plottable)")
            self.putValue(self.currentValue.value)
            self.putField("plottable", "0")
            return
        global gnuplotPipe
        global gnuplotPid
        format = self.currentItemFormat()
        iname = self.currentIName
        if format != plotFormat:
            if iname in gnuplotPipe:
                os.kill(gnuplotPid[iname], 9)
                del gnuplotPid[iname]
                gnuplotPipe[iname].terminate()
                del gnuplotPipe[iname]
            return
        base = self.createPointerValue(base, typeobj)
        if not iname in gnuplotPipe:
            gnuplotPipe[iname] = subprocess.Popen(["gnuplot"],
                    stdin=subprocess.PIPE)
            gnuplotPid[iname] = gnuplotPipe[iname].pid
        f = gnuplotPipe[iname].stdin;
        # On Ubuntu install gnuplot-x11
        f.write("set term wxt noraise\n")
        f.write("set title 'Data fields'\n")
        f.write("set xlabel 'Index'\n")
        f.write("set ylabel 'Value'\n")
        f.write("set grid\n")
        f.write("set style data lines;\n")
        f.write("plot  '-' title '%s'\n" % iname)
        for i in range(0, n):
            f.write(" %s\n" % base.dereference())
            base += 1
        f.write("e\n")

    def putSpecialArgv(self, value):
        """
        Special handling for char** argv.
        """
        n = 0
        p = value
        # p is 0 for "optimized out" cases. Or contains rubbish.
        try:
            if not self.isNull(p):
                while not self.isNull(p.dereference()) and n <= 100:
                    p += 1
                    n += 1
        except:
            pass

        with TopLevelItem(self, 'local.argv'):
            self.put('iname="local.argv",name="argv",')
            self.putItemCount(n, 100)
            self.putType('char **')
            if self.currentIName in self.expandedINames:
                p = value
                with Children(self, n):
                    for i in xrange(n):
                        self.putSubItem(i, p.dereference())
                        p += 1

    def extractPointer(self, thing, offset = 0):
        if isinstance(thing, int):
            bytes = self.extractBlob(thing, self.ptrSize()).toBytes()
        elif sys.version_info[0] == 2 and isinstance(thing, long):
            bytes = self.extractBlob(thing, self.ptrSize()).toBytes()
        elif isinstance(thing, Blob):
            bytes = thing.toBytes()
        else:
            # Assume it's a (backend specific) Value.
            bytes = self.toBlob(thing).toBytes()
        code = "I" if self.ptrSize() == 4 else "Q"
        return struct.unpack_from(code, bytes, offset)[0]


    # Parses a..b and  a.(s).b
    def parseRange(self, exp):

        # Search for the first unbalanced delimiter in s
        def searchUnbalanced(s, upwards):
            paran = 0
            bracket = 0
            if upwards:
                open_p, close_p, open_b, close_b = '(', ')', '[', ']'
            else:
                open_p, close_p, open_b, close_b = ')', '(', ']', '['
            for i in range(len(s)):
                c = s[i]
                if c == open_p:
                    paran += 1
                elif c == open_b:
                    bracket += 1
                elif c == close_p:
                    paran -= 1
                    if paran < 0:
                        return i
                elif c == close_b:
                    bracket -= 1
                    if bracket < 0:
                        return i
            return len(s)

        match = re.search("(\.)(\(.+?\))?(\.)", exp)
        if match:
            s = match.group(2)
            left_e = match.start(1)
            left_s =  1 + left_e - searchUnbalanced(exp[left_e::-1], False)
            right_s = match.end(3)
            right_e = right_s + searchUnbalanced(exp[right_s:], True)
            template = exp[:left_s] + '%s' +  exp[right_e:]

            a = exp[left_s:left_e]
            b = exp[right_s:right_e]

            try:
                # Allow integral expressions.
                ss = toInteger(self.parseAndEvaluate(s[1:len(s)-1]) if s else 1)
                aa = toInteger(self.parseAndEvaluate(a))
                bb = toInteger(self.parseAndEvaluate(b))
                if aa < bb and ss > 0:
                    return True, aa, ss, bb + 1, template
            except:
                pass
        return False, 0, 1, 1, exp

    def handleWatch(self, origexp, exp, iname):
        exp = str(exp).strip()
        escapedExp = self.hexencode(exp)
        #warn("HANDLING WATCH %s -> %s, INAME: '%s'" % (origexp, exp, iname))

        # Grouped items separated by semicolon
        if exp.find(";") >= 0:
            exps = exp.split(';')
            n = len(exps)
            with TopLevelItem(self, iname):
                self.put('iname="%s",' % iname)
                #self.put('wname="%s",' % escapedExp)
                self.put('name="%s",' % exp)
                self.put('exp="%s",' % exp)
                self.putItemCount(n)
                self.putNoType()
            for i in xrange(n):
                self.handleWatch(exps[i], exps[i], "%s.%d" % (iname, i))
            return

        # Special array index: e.g a[1..199] or a[1.(3).199] for stride 3.
        isRange, begin, step, end, template = self.parseRange(exp)
        if isRange:
            #warn("RANGE: %s %s %s in %s" % (begin, step, end, template))
            r = range(begin, end, step)
            n = len(r)
            with TopLevelItem(self, iname):
                self.put('iname="%s",' % iname)
                #self.put('wname="%s",' % escapedExp)
                self.put('name="%s",' % exp)
                self.put('exp="%s",' % exp)
                self.putItemCount(n)
                self.putNoType()
                with Children(self, n):
                    for i in r:
                        e = template % i
                        self.handleWatch(e, e, "%s.%s" % (iname, i))
            return

            # Fall back to less special syntax
            #return self.handleWatch(origexp, exp, iname)

        with TopLevelItem(self, iname):
            self.put('iname="%s",' % iname)
            self.put('name="%s",' % exp)
            self.put('wname="%s",' % escapedExp)
            if len(exp) == 0: # The <Edit> case
                self.putValue(" ")
                self.putNoType()
                self.putNumChild(0)
            else:
                try:
                    value = self.parseAndEvaluate(exp)
                    self.putItem(value)
                except RuntimeError:
                    self.currentType.value = " "
                    self.currentValue.value = "<no such value>"
                    self.currentChildNumChild = -1
                    self.currentNumChild = 0
                    self.putNumChild(0)


# Some "Enums"

# Encodings. Keep that synchronized with DebuggerEncoding in debuggerprotocol.h
Unencoded8Bit, \
Base64Encoded8BitWithQuotes, \
Base64Encoded16BitWithQuotes, \
Base64Encoded32BitWithQuotes, \
Base64Encoded16Bit, \
Base64Encoded8Bit, \
Hex2EncodedLatin1, \
Hex4EncodedLittleEndian, \
Hex8EncodedLittleEndian, \
Hex2EncodedUtf8, \
Hex8EncodedBigEndian, \
Hex4EncodedBigEndian, \
Hex4EncodedLittleEndianWithoutQuotes, \
Hex2EncodedLocal8Bit, \
JulianDate, \
MillisecondsSinceMidnight, \
JulianDateAndMillisecondsSinceMidnight, \
Hex2EncodedInt1, \
Hex2EncodedInt2, \
Hex2EncodedInt4, \
Hex2EncodedInt8, \
Hex2EncodedUInt1, \
Hex2EncodedUInt2, \
Hex2EncodedUInt4, \
Hex2EncodedUInt8, \
Hex2EncodedFloat4, \
Hex2EncodedFloat8, \
IPv6AddressAndHexScopeId, \
Hex2EncodedUtf8WithoutQuotes, \
DateTimeInternal \
    = range(30)

# Display modes. Keep that synchronized with DebuggerDisplay in watchutils.h
StopDisplay, \
DisplayImageData, \
DisplayUtf16String, \
DisplayImageFile, \
DisplayLatin1String, \
DisplayUtf8String \
    = range(6)


def mapForms():
    return "Normal,Compact"

def arrayForms():
    if hasPlot():
        return "Normal,Plot"
    return "Normal"

