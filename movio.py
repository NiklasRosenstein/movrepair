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

import io
import os
import struct


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
    if isinstance(fp, bytes):
      fp = io.BytesIO(fp)
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

  def to_atomd(self, parent=None):
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
    return MovAtomD(self.tag, self.read_data(), parent=parent)


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

  def __init__(self, tag, data=None, atoms=None, parent=None):
    assert isinstance(tag, bytes), type(tag)
    assert len(tag) == 4, len(tag)
    self.tag = tag
    self.data = data
    self.atoms = atoms
    self.parent = parent

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
    self.atoms = [x.to_atomd(self) for x in MovAtomR.make_root(fp).iter_atoms()]
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
