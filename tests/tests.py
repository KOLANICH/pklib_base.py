#!/usr/bin/env python3
import os
import sys
import unittest
from pathlib import Path
import mmap
from secrets import token_bytes

thisDir = Path(__file__).resolve().absolute().parent
repoRootDir = thisDir.parent

sys.path.insert(0, str(repoRootDir))

from collections import OrderedDict
dict = OrderedDict

from pklib_base import logIntoSize, maskIntoSize, dictSizeIntoLog, logIntoMask, dictSizeIntoMask


class Tests(unittest.TestCase):
	TABLE = [
		(4096, 0b111111, 6),
		(2048, 0b011111, 5),
		(1024, 0b001111, 4),
		(512,  0b000111, 3),
		(256,  0b000011, 2),
		(128,  0b000001, 1),
	]

	def testLogIntoSize(self):
		for size, mask, log in self.__class__.TABLE:
			with self.subTest(log=log, size=size):
				self.assertEqual(logIntoSize(log), size)

	def testMaskIntoSize(self):
		for size, mask, log in self.__class__.TABLE:
			with self.subTest(mask=mask, size=size):
				self.assertEqual(maskIntoSize(mask), size)

	def testDictSizeIntoLog(self):
		for size, mask, log in self.__class__.TABLE:
			with self.subTest(log=log, size=size):
				self.assertEqual(dictSizeIntoLog(size), log)

	def testLogIntoMask(self):
		for size, mask, log in self.__class__.TABLE:
			with self.subTest(mask=mask, log=log):
				self.assertEqual(logIntoMask(log), mask)

	def testDictSizeIntoMask(self):
		for size, mask, log in self.__class__.TABLE:
			with self.subTest(mask=mask, size=size):
				self.assertEqual(dictSizeIntoMask(size), mask)

if __name__ == '__main__':
	unittest.main()
