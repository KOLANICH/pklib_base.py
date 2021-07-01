import ctypes
import platform
import typing
from collections.abc import ByteString
from enum import IntEnum
from functools import partial
from io import IOBase
from struct import Struct
from zlib import crc32 as crc32_zlib

from .enums import CompressionType

# pylint:disable=too-few-public-methods


def crc32(data: ByteString, value: int = 0) -> int:
	return (~crc32_zlib(data, value)) & 0xFFFFFFF


def decodeHeader(compressed: ByteString):
	compressionType = CompressionType(compressed[0])
	dictSizeLog = compressed[1]
	return compressionType, logIntoSize(dictSizeLog)


def logIntoSize(log: int) -> int:
	return 1 << (log + 6)


def maskIntoSize(mask: int) -> int:
	return logIntoSize(mask.bit_length())


def dictSizeIntoLog(dictSize: int) -> int:
	mask = 0
	if dictSize < 128:
		raise ValueError("Dict sizes less than 128 are unsupported!")

	return (dictSize).bit_length() - 7


def logIntoMask(dictSizeLog: int) -> int:
	return (1 << dictSizeLog) - 1


def dictSizeIntoMask(dictSize: int) -> int:
	return logIntoMask(dictSizeIntoLog(dictSize))


class PklibError(IntEnum):
	ok = CMP_NO_ERROR = 0
	invalidDictSize = CMP_INVALID_DICTSIZE = 1
	invalidMode = CMP_INVALID_MODE = 2
	badData = CMP_BAD_DATA = 3
	abort = CMP_ABORT = 4


class CommonSizeConstants:
	__slots__ = ("OUT_BUFF_SIZE", "BUFF_SIZE")

	def __init__(self, OUT_BUFF_SIZE: int, BUFF_SIZE: int):
		self.OUT_BUFF_SIZE = OUT_BUFF_SIZE
		self.BUFF_SIZE = BUFF_SIZE


class CommonSizeConstantsCtypes(ctypes.Structure):
	__slots__ = CommonSizeConstants.__slots__ + ("ownSize",)
	_fields_ = [
		("ownSize", ctypes.c_size_t),
		("OUT_BUFF_SIZE", ctypes.c_size_t),
		("BUFF_SIZE", ctypes.c_size_t),
	]


class LUTSizeConstants:
	__slots__ = ("DIST_SIZES", "CH_BITS_ASC_SIZE", "LENS_SIZES")

	def __init__(self, DIST_SIZES: int, CH_BITS_ASC_SIZE: int, LENS_SIZES: int):
		self.DIST_SIZES = DIST_SIZES
		self.CH_BITS_ASC_SIZE = CH_BITS_ASC_SIZE
		self.LENS_SIZES = LENS_SIZES


class LUTSizeConstantsCtypes(ctypes.Structure):
	__slots__ = LUTSizeConstants.__slots__ + ("ownSize",)
	_fields_ = [
		("ownSize", ctypes.c_size_t),
		("DIST_SIZES", ctypes.c_size_t),
		("CH_BITS_ASC_SIZE", ctypes.c_size_t),
		("LENS_SIZES", ctypes.c_size_t),
	]


specializedSizeConstantsHeader = (("ownSize", ctypes.c_size_t),)


def parseCommonSizeConstants(commonSizes: CommonSizeConstantsCtypes) -> CommonSizeConstants:
	if int(commonSizes.ownSize) != ctypes.sizeof(CommonSizeConstantsCtypes):
		raise ValueError("CommonSizeConstantsCtypes contents has changed!", commonSizes.ownSize, ctypes.sizeof(CommonSizeConstantsCtypes))

	return CommonSizeConstants(int(commonSizes.OUT_BUFF_SIZE), int(commonSizes.BUFF_SIZE))


def _getSizeConstants1(lib, funcName, resCtypesType, resInternalType, parserFunc):
	getSpecializedSizeConstantsT = getattr(lib, funcName)
	getSpecializedSizeConstantsT.argtypes = []
	getSpecializedSizeConstantsT.restype = resCtypesType
	sizeConstants = getSpecializedSizeConstantsT()

	return parserFunc(sizeConstants)


def getCommonSizeConstants(lib):
	return _getSizeConstants1(lib, "getCommonSizeConstants", CommonSizeConstantsCtypes, CommonSizeConstants, parseCommonSizeConstants)


def parseLUTSizeConstants(lutsSizes: LUTSizeConstantsCtypes) -> LUTSizeConstants:
	if int(lutsSizes.ownSize) != ctypes.sizeof(LUTSizeConstantsCtypes):
		raise ValueError("LUTSizeConstantsCtypes contents has changed!", lutsSizes.ownSize, ctypes.sizeof(LUTSizeConstantsCtypes))

	return LUTSizeConstants(int(lutsSizes.DIST_SIZES), int(lutsSizes.CH_BITS_ASC_SIZE), int(lutsSizes.LENS_SIZES))


def getLUTSizeConstants(lib):
	return _getSizeConstants1(lib, "getLUTSizeConstants", LUTSizeConstantsCtypes, LUTSizeConstants, parseLUTSizeConstants)


def inputCallbackStream(inputStream: IOBase, buf: ctypes.POINTER(ctypes.c_char_p), chunkSize: ctypes.POINTER(ctypes.c_uint), param: ctypes.POINTER(None)) -> ctypes.c_uint:  # pylint:disable=unused-argument
	bufT = ctypes.c_byte * chunkSize[0]
	bufPtrT = ctypes.POINTER(bufT)
	bufArrPtr = ctypes.cast(buf, bufPtrT)

	countRead = inputStream.readinto(bufArrPtr[0])
	return countRead


def outputCallbackStream(outputStream: IOBase, buf: ctypes.POINTER(ctypes.c_char_p), chunkSize: ctypes.POINTER(ctypes.c_uint), param: ctypes.POINTER(None)) -> None:  # pylint:disable=unused-argument
	bufT = ctypes.c_byte * chunkSize[0]
	bufPtrT = ctypes.POINTER(bufT)
	bufArrPtr = ctypes.cast(buf, bufPtrT)
	outputStream.write(bufArrPtr[0])


def _genCtypesFuncArgsList(f, skip: int = 0):
	return (f.__annotations__.get("return", None),) + tuple(f.__annotations__.get(argName, None) for argName in f.__code__.co_varnames[: f.__code__.co_argcount])[skip:]


ReadFunT = ctypes.CFUNCTYPE(*_genCtypesFuncArgsList(inputCallbackStream, 1))
WriteFunT = ctypes.CFUNCTYPE(*_genCtypesFuncArgsList(outputCallbackStream, 1))


def getStreamCallbacks(inputStream: IOBase, outputStream: IOBase):
	icb = ReadFunT(partial(inputCallbackStream, inputStream))
	ocb = WriteFunT(partial(outputCallbackStream, outputStream))
	return icb, ocb


def getLibraryFileName(nameNoPrefix):
	if platform.system() == "Windows":
		return "lib" + nameNoPrefix + ".dll"

	return "lib" + nameNoPrefix + ".so"


def _initLibrary(func, internalStateStructName, specializedSizeConstantsFields: typing.Tuple[typing.Tuple[str, typing.Any]], getFieldsForInternalStateStructure):
	nameNoPrefix = func.__name__
	nameNoPrefixFirstCapital = nameNoPrefix[0].upper() + nameNoPrefix[1:]

	lutsLib = ctypes.CDLL(getLibraryFileName("pkwareLUT"))
	commonLib = lutsLib

	lib = ctypes.CDLL(getLibraryFileName(nameNoPrefix))

	class SpecializedSizeConstantsT:
		__slots__ = tuple(el[0] for el in specializedSizeConstantsFields)

		def __init__(self, **kwargs):
			for k, defaultV in specializedSizeConstantsFields:
				setattr(self, k, kwargs.get(k, defaultV))

	SpecializedSizeConstantsT.__name__ = nameNoPrefixFirstCapital + "SizeConstantsT"

	class SpecializedSizeConstantsCtypesT(ctypes.Structure):
		__slots__ = SpecializedSizeConstantsT.__slots__ + ("ownSize",)
		_fields_ = specializedSizeConstantsHeader + tuple((el[0], ctypes.c_size_t) for el in specializedSizeConstantsFields)

	SpecializedSizeConstantsCtypesT.__name__ = nameNoPrefixFirstCapital + "SizeConstantsCtypesT"

	def _getSizeConstants(lib, nameNoPrefixFirstCapital) -> SpecializedSizeConstantsT:
		constantsGetterName = "get" + nameNoPrefixFirstCapital + "SizeConstants"
		if hasattr(lib, constantsGetterName):

			def parserFunc(sizeConstants):
				if int(sizeConstants.ownSize) != ctypes.sizeof(SpecializedSizeConstantsCtypesT):
					raise ValueError(SpecializedSizeConstantsCtypesT.__name__ + " contents has changed!", sizeConstants.ownSize, ctypes.sizeof(SpecializedSizeConstantsCtypesT))

				kwargs = {}
				for k, _ in specializedSizeConstantsFields:
					kwargs[k] = int(getattr(sizeConstants, k))

				return SpecializedSizeConstantsT(**kwargs)

			return _getSizeConstants1(lib, constantsGetterName, SpecializedSizeConstantsCtypesT, SpecializedSizeConstantsT, parserFunc)
		else:
			sizeConstants = SpecializedSizeConstantsT()
		return sizeConstants

	def constructInternalStateStruct(name, commonSizes, lutSizes, sizeConstants, getFieldsForInternalStateStructure):
		class InternalStateStructT(ctypes.Structure):
			_fields_ = getFieldsForInternalStateStructure(commonSizes, lutSizes, sizeConstants)
			__slots__ = tuple(el[0] for el in _fields_)

		InternalStateStructT.__name__ = name

		if sizeConstants.internalStructSize is not None:
			if sizeConstants.internalStructSize != ctypes.sizeof(InternalStateStructT):
				raise ValueError(InternalStateStructT.__name__ + " contents has changed!", sizeConstants.internalStructSize, ctypes.sizeof(InternalStateStructT))
		else:
			sizeConstants.internalStructSize = ctypes.sizeof(InternalStateStructT)

		return InternalStateStructT

	lutSizes = getLUTSizeConstants(lutsLib)
	commonSizes = getCommonSizeConstants(commonLib)

	sizeConstants = _getSizeConstants(lib, nameNoPrefixFirstCapital)
	InternalStateStructT = constructInternalStateStruct(internalStateStructName, commonSizes, lutSizes, sizeConstants, getFieldsForInternalStateStructure)

	ctypesFunc = getattr(lib, nameNoPrefix)

	ctypesFunc.argtypes = [func.__annotations__[argName] for argName in func.__code__.co_varnames[: func.__code__.co_argcount]]
	ctypesFunc.restype = func.__annotations__["return"]

	return lib, InternalStateStructT, sizeConstants
