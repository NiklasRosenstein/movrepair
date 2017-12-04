# The MIT License (MIT)
#
# Copyright (c) 2017 Niklas Rosenstein
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import division, print_function
import argparse
import collections
import os
import struct
import sys

AtomHeader = collections.namedtuple('AtomHeader', 'size tag')


class MovAtomReader:

  def __init__(self, fp):
    self._file = fp
    self._bytes_read = 0
    start_pos = fp.tell()
    fp.seek(0, os.SEEK_END)
    self._size = fp.tell() - start_pos
    fp.seek(start_pos)

  def read_atom(self): # -> AtomHeader
    header = self._file.read(8)
    self._bytes_read += len(header)
    if len(header) not in (0, 8):
      raise ValueError('invalid MOV file, expected 8 header bytes, got {}'.format(len(header)))
    if not header:
      return None
    return AtomHeader(struct.unpack('>I', header[:4])[0]-8, header[4:])

  def read_data(self, size):
    data = self._file.read(size)
    self._bytes_read += len(data)
    if len(data) != size:
      assert self._file.tell() == self._size
      assert self._bytes_read == self._size
    return data

  def skip(self, size):
    if self._bytes_read + size > self._size:
      delta = self._size - self._bytes_read
      self._bytes_read = self._size
      self._file.seek(0, os.SEEK_END)
      assert self._file.tell() == self._size
      return delta
    else:
      self._bytes_read += size
      self._file.seek(size, os.SEEK_CUR)
      return size

  def size(self):
    return self._size


class MovAtomWriter:

  def __init__(self, fp):
    self._file = fp

  def write_atom(self, atom):
    assert isinstance(atom.tag, bytes), type(atom.tag)
    assert len(atom.tag) == 4, len(atom.tag)
    self._file.write(struct.pack('>I', atom.size + 8))
    self._file.write(atom.tag)

  def write_data(self, data):
    self._file.write(data)


def sizeof_fmt(num, suffix='B'):
  # Thanks to https://stackoverflow.com/a/1094933
  for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
    if abs(num) < 1024.0:
      return "%3.1f%s%s" % (num, unit, suffix)
    num /= 1024.0
  return "%.1f%s%s" % (num, 'Yi', suffix)


def main():
  parser = argparse.ArgumentParser(add_help=False)
  parser.add_argument('file')
  parser.add_argument('-h', action='store_true', help='Human readable size information.')
  parser.add_argument('-o', '--output', help='The repaired output file.')
  parser.add_argument('--repair', help='A file to repair using the input file.')
  args = parser.parse_args()
  bfmt = sizeof_fmt if args.h else str

  if not args.output and not args.repair:
    with open(args.file, 'rb') as fp:
      reader = MovAtomReader(fp)
      print('total file size:', bfmt(reader.size()))
      while True:
        atom = reader.read_atom()
        if not atom: break
        name = atom.tag.decode('ascii', 'ignore')
        print('* {} ({})'.format(atom.tag.decode('ascii', 'ignore'), bfmt(atom.size)), end='')
        #delta = reader.skip(atom.size)
        data = reader.read_data(atom.size)
        delta = len(data)
        if delta != atom.size:
          print(' [error: could only read {}]'.format(bfmt(delta)))
        else:
          print()

        if b'moov' in data:
          idx = data.index(b'moov')
          hdr = data[idx-4:idx+4]
          size = struct.unpack('>I', hdr[:4])[0]
          print('moov:', idx, size, hdr)
    return 0

  if not args.output:
    name, ext = os.path.splitext(args.repair)
    args.output = name + '-fixed' + ext

  with open(args.file, 'rb') as fp:
    reference = MovAtomReader(fp)
    begin_atoms = []
    end_atoms = []
    while True:
      atom = reference.read_atom()
      if not atom or atom.tag == b'mdat':
        if atom: reference.skip(atom.size)
        break
      begin_atoms.append((atom, reference.read_data(atom.size)))
    while True:
      atom = reference.read_atom()
      if not atom: break
      end_atoms.append((atom, reference.read_data(atom.size)))

  print('Output file:', args.output)
  with open(args.repair, 'rb') as fp:
    torepair = MovAtomReader(fp)
    with open(args.output, 'wb') as fp:
      writer = MovAtomWriter(fp)

      print('Writing begin atoms from working reference file ...')
      for atom, data in begin_atoms:
        print('  *', atom.tag.decode('ascii', 'ignore'))
        writer.write_atom(AtomHeader(len(data), atom.tag))
        writer.write_data(data)

      end_size = sum(len(x[1]) for x in end_atoms)
      print('Size of atoms following mdat in reference file:', bfmt(end_size))

      # Search for the mdat atom in the file that is to be repaired.
      print('Looking for mdat section of broken file ...')
      while True:
        atom = torepair.read_atom()
        if not atom: break
        if atom.tag == b'mdat':
          data = torepair.read_data(atom.size)
          data = data[:-end_size]
          print('Writing mdat of broken file ... ({})'.format(bfmt(len(data))))
          writer.write_atom(AtomHeader(len(data), atom.tag))
          writer.write_data(data)
        else:
          torepair.skip(atom.size)

      print('Writing end atoms from working reference file ...')
      for atom, data in end_atoms:
        print('  *', atom.tag.decode('ascii', 'ignore'))
        writer.write_atom(AtomHeader(len(data), atom.tag))
        writer.write_data(data)

  print('Done.')


if __name__ == '__main__':
  sys.exit(main())
