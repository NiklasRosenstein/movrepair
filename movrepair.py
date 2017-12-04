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
"""
References:

* http://mirror.informatimago.com/next/developer.apple.com/documentation/QuickTime/APIREF/INDEX/atomalphaindex.htm
* https://developer.apple.com/library/content/documentation/QuickTime/QTFF/QTFFChap2/qtff2.html#//apple_ref/doc/uid/TP40000939-CH204-56313
"""

from __future__ import division, print_function
import argparse
import collections
import io
import os
import struct
import sys


class MovFileError(Exception):
  pass


class MovAtomR(object):
  """
  Represents a section in a readable file-like object that can be interpreted
  as a .MOV atom. To use this object, #read_header() should be called first
  to fill the #size and #tag members.
  """

  @classmethod
  def make_root(cls, fp):
    ar = cls(fp, is_root_atom=True)
    ar.is_root_atom = True
    return ar

  def __init__(self, fp, is_root_atom=False):
    self.file = fp
    self.size = 0
    self.tag = None
    self.bytes_read = 0
    self.atom_begin = None
    self.is_root_atom = is_root_atom
    if self.is_root_atom:
      self.size = get_file_size_via_seek(fp)

  def __repr__(self):
    if self.is_root_atom:
      return '<MovAtomR (root)>'
    else:
      return '<MovAtomR size={!r} tag={!r}>'.format(self.size, self.tag)

  def read_header(self):
    """
    Extracts the .MOV header of this atom from the current file position.
    Raises a #RuntimeError if the header for this atom has already been read.
    """

    if self.is_root_atom:
      raise RuntimeError('can not read header of root MovAtomR')
    if self.bytes_read != 0:
      raise RuntimeError('atom header already read')
    self.atom_begin = self.file.tell()
    header = self.file.read(8)
    if len(header) != 8:
      raise MovFileError('reached EOF while reading atom header')
    self.size = struct.unpack('>I', header[:4])[0]
    self.tag = header[4:]
    self.bytes_read = 8

  def read_data(self, length=None, allow_incomplete=False):
    """
    Reads the data of this atom. If the header of this atom has not been read
    yet, it will be done automatically. If *allow_incomplete* is #False, a
    #MovFileError will be raised if not the full contents could be read.

    If *length* is not #None, only *length* bytes will be read at max. Calling
    this method again will read the next *length* bytes or to the end of the
    atom.
    """

    if self.is_root_atom:
      raise RuntimeError('can not read data from root MovAtomR')
    if self.bytes_read == 0:
      self.read_header()
    nbytes = self.size - self.bytes_read
    assert nbytes >= 0
    if length is not None:
      nbytes = min(nbytes, length)
    data = self.file.read(nbytes)
    self.bytes_read += len(data)
    if len(data) != nbytes and not allow_incomplete:
      raise MovFileError('reached EOF while reading "{}" atom data'.format(
        self.tag.decode('ascii', 'ignore')))
    return data

  def iter_data(self, chunksize, allow_incomplete=False):
    while True:
      data = self.read_data(chunksize, allow_incomplete)
      if not data: break
      yield data

  def skip(self):
    """
    Skip over the contents of this atom. Does nothing if the data of this atom
    has already been read with #read_data(). This is used in #iter_atoms() to
    ensure that the file points to the next atom in the next step of iteration.
    """

    if self.bytes_read == 0:
      self.read_header()
    nbytes = self.size - self.bytes_read
    assert nbytes >= 0
    if nbytes > 0:
      self.file.seek(nbytes, os.SEEK_CUR)
      self.bytes_read += nbytes

  def iter_atoms(self):
    """
    Creates a new #MovAtomR for every sub-atom. The header of this atom will
    already be read.
    """

    if not self.is_root_atom and self.bytes_read == 0:
      self.read_header()
    while self.bytes_read < self.size:
      atom = type(self)(self.file)
      atom.read_header()
      yield atom
      atom.skip()
      self.bytes_read += atom.bytes_read
    if not self.is_root_atom and self.bytes_read != self.size:
      raise MovFileError('sub-atoms exceed parent atom size: "{}"'.format(
        self.tag.decode('ascii', 'ignore')))

  def to_atomd(self):
    """
    Converts this atom to a #MovAtomD object. Requires that no data of this
    atom has been read past the header.
    """

    if self.is_root_atom:
      raise ValueError('can not convert root MovAtomR to MovAtomD')
    if self.bytes_read == 0:
      self.read_header()
    if self.bytes_read != 8:
      raise RuntimeError('MovAtomR data has already been read past '
          'header, can not convert to MovAtomD')
    return MovAtomD(self.tag, self.read_data())


class MovAtomD(object):
  """
  Represents a full .MOV atom in memory (not streaming from a file, like
  #MovAtomR). This atom may either contain either a block of raw data (leaf
  node), or other atoms.

  Once a #MovAtomD instance is obtained (eg. by converting from a #MovAtomR),
  it will most likely be in leaf-node form. However, if the atom type is known
  to contain sub-atoms, it can be split into sub-atoms using #subatomize()
  function or #iter_atoms() method.
  """

  def __init__(self, tag, data=None, atoms=None):
    assert isinstance(tag, bytes), type(tag)
    assert len(tag) == 4, len(tag)
    self.tag = tag
    self.data = data
    self.atoms = atoms

  def __repr__(self):
    if self.is_leaf():
      return '<MovAtomD tag={!r} size={} (leaf)>'.format(self.tag, self.calculate_size())
    else:
      return '<MovAtomD tag={!r} size={} len(atoms)={}>'.format(self.tag, self.calculate_size(), len(self.atoms))

  def is_leaf(self):
    return self.atoms is None

  def edit(self):
    """
    Ensures that the #data member of this #MovAtomD is a #bytearray object.
    If this is not a leaf-atom, a #RuntimeError will be raised.
    """

    if not self.is_leaf():
      raise RuntimeError('can not use MovAtomD.edit() on non-leaf atom')
    if not isinstance(self.data, bytearray):
      self.data = bytearray(self.data)
    return self.data

  def split(self):
    """
    Given this is a leaf-atom, splits the #data of the atom assuming that it
    contains sub-atoms. The #data member will be set to #None and the #atoms
    member will contain a list of the sub-atoms (as #MovAtomD).
    """

    if not self.is_leaf():
      raise ValueError('MovAtomD is already split')
    fp, self.data = io.BytesIO(self.data), None
    self.atoms = [x.to_atomd() for x in MovAtomR.make_root(fp).iter_atoms()]
    return self

  def iter_atoms(self):
    """
    Iterates over the sub-atoms of this atom. If the atom is still treated as
    a leaf-node, #split() will be used automatically.
    """

    if self.is_leaf():
      self.split()
    return iter(self.atoms)

  def find_atoms(self, *tpath):
    """
    Finds sub-atoms by tag-name. Automatically uses #split() on any matching
    sub-atom. *tpath* must be one or more tag names. The first tag-name is
    resolved in this atom, the second tag-name in the respectively matching
    tag-name, etc.

    Returns a list of matching atoms.
    """

    result = []
    def recurse(atom, curr, *tpath):
      for sub_atom in atom.iter_atoms():
        if sub_atom.tag == curr:
          if not tpath:
            result.append(sub_atom)
          else:
            recurse(sub_atom, *tpath)
    recurse(self, *tpath)
    return result

  def calculate_size(self):
    if self.is_leaf():
      return len(self.data) + 8
    else:
      return sum(x.calculate_size() for x in self.atoms) + 8

  def write(self, fp):
    """
    Write this atom to a file.
    """

    size = self.calculate_size()
    with MovAtomW(fp, size, self.tag) as writer:
      if self.is_leaf():
        writer.write(self.data)
      else:
        for atom in self.atoms:
          atom.write(writer)


class MovAtomW(object):
  """
  A write-only .MOV atom.
  """

  @classmethod
  def make_root(cls, fp):
    return cls(fp, None, None)

  def __init__(self, fp, size, tag):
    if tag is not None:
      assert isinstance(tag, bytes), type(tag)
      assert len(tag) == 4, len(tag)
      if size < 8:
        raise MovFileError('atom size must be >= 8 (atom: "{}")'.format(
            tag.decode('ascii', 'ignore')))
      fp.write(struct.pack('>I', size))
      fp.write(tag)
      self.bytes_written = 8
    else:
      assert size is None
      self.bytes_written = 0
    self.file = fp
    self.size = size
    self.tag = tag

  def __enter__(self):
    return self

  def __exit__(self, e_type, e_val, e_tb):
    if e_val is None:
      self.finalize()

  @property
  def is_root_atom(self):
    return self.size is None

  def write(self, data):
    if not self.is_root_atom and self.bytes_written + len(data) > self.size:
      raise MovFileError('atom "{}" data excess'.format(self.tag.decode('ascii', 'ignore')))
    self.file.write(data)
    self.bytes_written += len(data)

  def finalize(self):
    if not self.is_root_atom and self.bytes_written != self.size:
      raise MovFileError('atom "{}" data size mismatch (got {}, expected {})'
          .format(self.tag.decode('ascii', 'ignore'), self.bytes_written, self.size))


def get_file_size_via_seek(fp):
  pos = fp.tell()
  fp.seek(0, os.SEEK_END)
  try:
    return fp.tell()
  finally:
    fp.seek(pos)


def sizeof_fmt(num, suffix='B'):
  # Thanks to https://stackoverflow.com/a/1094933
  for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
    if abs(num) < 1024.0:
      return "%3.1f%s%s" % (num, unit, suffix)
    num /= 1024.0
  return "%.1f%s%s" % (num, 'Yi', suffix)


def repair_file(reference, broken, output):
  """
  Tries to repair the *broken* file using the *reference* file and writes it
  to the *output* file. This function will transfer all sections from the
  *reference* file to the *output* file, except for the `mdat` atom which is
  taken from the *broken* file instead.

  We assume the order of atoms in the reference file is the same as the
  order of atoms in the broken input file.
  """

  # Extract the meta information atoms from the reference file.
  reference_atoms = collections.OrderedDict()
  end_file_offset = 0
  for atom in MovAtomR.make_root(reference).iter_atoms():
    if atom.tag != b'mdat':
      # We keep track of the number of bytes used in the reference file for
      # atoms after the mdat atom.
      if b'mdat' in reference_atoms:
        end_file_offset += atom.size

      # Read in the full contents of this atom into memory.
      atom = atom.to_atomd()

      # Ensure that we have the moov atom after the mdat atom. We need
      # this for later as we need to update it after we write the broken
      # file's mdat.
      if b'moov' in reference_atoms:
        reference_atoms[b'moov'] = reference_atoms.pop(b'moov')

    reference_atoms[atom.tag] = atom

  # Find the `mdat` atom in the broken input file. Do NOT read it so we
  # can stream its contents to the output file later.
  for atom in MovAtomR.make_root(broken).iter_atoms():
    if atom.tag == b'mdat':
      mdat = atom
      break
  else:
    print('error: could not find mdat atom in broken input file')
    return 1

  # We assume that the header of the mdat is broken and we need to adjust
  # for the atoms after the mdat section (#end_file_offset).
  mdat_size = get_file_size_via_seek(mdat.file) - mdat.atom_begin - end_file_offset
  print('Broken file\'s mdat size adjusted from {} to {}'.format(
      sizeof_fmt(mdat.size), sizeof_fmt(mdat_size)))
  mdat.size = mdat_size

  # Find a new duration for the new file based on the size of the reference
  # file's duration and sample size in bytes.
  def get_new_duration(atom):
    time_scale, ref_duration = struct.unpack('>II', atom.data[12:20])
    new_duration = int(round(mdat.size / reference_atoms[b'mdat'].size * ref_duration))
    print('Adjusting "{}" duration from {}s to {}s.'.format(
        atom.tag.decode('ascii', 'ignore'),
        ref_duration/time_scale,
        new_duration/time_scale))
    return new_duration
  moov = reference_atoms[b'moov']
  mvhd = moov.find_atoms(b'mvhd')[0]
  new_duration = get_new_duration(mvhd)
  new_duration_packed = struct.pack('>I', new_duration)

  updated_atoms = []
  mvhd.edit()[16:20] = new_duration_packed
  updated_atoms.append(mvhd)
  for tkhd in moov.find_atoms(b'trak', b'tkhd'):
    updated_atoms.append(tkhd)
    tkhd.edit()[20:24] = new_duration_packed
  for elst in moov.find_atoms(b'trak', b'edts', b'elst'):
    updated_atoms.append(elst)
    # NOTE: There could be multiple entries in the reference file or in the
    #       broken file. The former we don't care about, but the latter we
    #       can't know. We'll just assume one entry.
    flag = struct.unpack('>I', elst.data[:4])[0]
    rate = struct.unpack('>I', elst.data[16:20])[0]
    values = [flag, 1, new_duration, 0, rate]
    elst.edit()[:] = struct.pack('>IIIII', *values)
  for mdhd in moov.find_atoms(b'trak', b'mdia', b'mdhd'):
    updated_atoms.append(mdhd)
    mdhd.edit()[16:20] = struct.pack('>I', get_new_duration(mdhd))

  print('Updated moov atoms:', ', '.join(x.tag.decode('ascii', 'ignore') for x in updated_atoms))

  # Write the reference file's atoms and the mdat from the broken file.
  for atom in reference_atoms.values():
    if atom.tag == b'mdat':
      with MovAtomW(output, mdat_size, atom.tag) as writer:
        for chunk in mdat.iter_data(1024):
          writer.write(chunk)
    else:
      atom.write(output)
  return 0


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('file')
  parser.add_argument('-o', '--output', help='The repaired output file.')
  parser.add_argument('-R', '--repair', help='A file to repair using the input file.')
  args = parser.parse_args()

  if args.repair:
    if not args.output:
      name, ext = os.path.splitext(args.repair)
      args.output = name + '-fixed' + ext
    print('Output file:', args.output)
    with open(args.file, 'rb') as reference, \
        open(args.repair, 'rb') as broken, \
        open(args.output, 'wb') as output:
      return repair_file(reference, broken, output)
  else:
    with open(args.file, 'rb') as fp:
      print('file size:', sizeof_fmt(get_file_size_via_seek(fp)))
      for atom in MovAtomR.make_root(fp).iter_atoms():
        print('* {} ({})'.format(atom.tag.decode('ascii', 'ignore'), sizeof_fmt(atom.size)))
    return 0


if __name__ == '__main__':
  sys.exit(main())
