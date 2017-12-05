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

from movio import MovAtomR, MovAtomW
from movutils import UnpackContext, Field, ListField, StringField, Struct
import collections
import struct
import sys


class SubAtomsUnpackContext(UnpackContext):

  def __init__(self, atom, struct_type, parent=None):
    super(SubAtomsUnpackContext, self).__init__(struct_type, parent)
    self.atom = atom


class SubAtomsField(Field):

  def __init__(self, name, supported_atoms):
    super(SubAtomsField, self).__init__(name, None)
    if isinstance(supported_atoms, dict):
      self.supported_atoms = supported_atoms
    else:
      self.supported_atoms = {}
      for atom_type in supported_atoms:
        self.supported_atoms[atom_type.__name__.encode('ascii')] = atom_type
    self.reverse_supported_atoms = {v: k for k, v in self.supported_atoms.items()}

  def size(self):
    return None

  def unpack_from_stream(self, ctx, fp):
    result = []
    for atom in MovAtomR.make_root(fp).iter_atoms():
      struct_type = self.supported_atoms.get(atom.tag)
      if struct_type:
        ctx = SubAtomsUnpackContext(atom, struct_type, ctx)
        atom_obj = struct_type.unpack(atom.read_data(), ctx)
        if type(atom_obj) not in self.reverse_supported_atoms:
          raise RuntimeError('unpacked atom is not in reverse table')
        result.append(atom_obj)
      else:
        print('warning: unsupported atom type in {}: {!r}'.format(
            ctx.struct_type.__name__, atom.tag))
    return result

  def pack_into_stream(self, struct_type, fp, atoms):
    for atom in atoms:
      tag = self.reverse_supported_atoms.get(type(atom))
      if tag is None:
        raise ValueError('{} is not in reverse_supported_atoms'.format(
            type(atom).__name__))
      data = atom.pack()
      with MovAtomW(fp, len(data), tag) as writer:
        writer.write_data(data)


class hdlr(Struct):  # Handle Reference Atom (requires SubAtomsUnpackContext)
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('comp_type', '>I'),
    Field('comp_subtype', '>I'),
    Field('comp_manf', '>I'),
    Field('comp_flags', '>I'),
    Field('comp_flags_mask', '>I'),
    StringField('comp_name', length=lambda ctx: ctx.atom.size-24-8)
  ]


class tkhd(Struct):  # Track Header Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('creation_time', '>I'),
    Field('modification_time', '>I'),
    Field('track_id', '>I'),
    Field('?', '4x'),
    Field('duration', '>I'),
    Field('?', '8x'),
    Field('layer', '>H'),
    Field('alternate_group', '>H'),
    Field('volume', '>H'),
    Field('?', '2x'),
    Field('matrix_structure', '>9I'),
    Field('track_width', '>I'),
    Field('track_height', '>I')
  ]


class mdhd(Struct):  # Media Header Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('creation_time', '>I'),
    Field('modification_time', '>I'),
    Field('time_scale', '>I'),
    Field('duration', '>I'),
    Field('language', '>H'),
    Field('quality', '>H')
  ]


class mvhd(Struct):  # Movie Header Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('creation_time', '>I'),
    Field('modification_time', '>I'),
    Field('time_scale', '>I'),
    Field('duration', '>I'),
    Field('preferred_rate', '>I'),
    Field('preferred_volume', '>H'),
    Field('?', '10x'),
    Field('matrix_structure', '>9I'),
    Field('preview_time', '>I'),
    Field('preview_duration', '>I'),
    Field('post_time', '>I'),
    Field('selection_time', '>I'),
    Field('current_time', '>I'),
    Field('next_track_id', '>I'),
  ]


class stts(Struct):  # Time-to-Sample Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('nitems?', '>I', lambda s: len(s.table)),
    ListField('table', '>II', times='nitems')
  ]


class sample_description(Struct):
  _fields_ = [
    Field('size?', '>I', lambda s: len(s.data) + 16),
    Field('data_format', '>I'),
    Field('?', '6x'),
    Field('data_reference_index', '>H'),
    StringField('data', length=lambda ctx: ctx['size'] - 16)
  ]


class stsd(Struct):  # Sample Description Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('nitems?', '>I', lambda s: len(s.descriptions)),
    ListField('descriptions', sample_description, times='nitems')
  ]


class stss(Struct):  # Sync Sample Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('nitems?', '>I', lambda s: len(s.table)),
    ListField('table', '>I', times='nitems')
  ]


class stsz(Struct):  # Sample Size Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('size', '>I'),
    Field('nitems?', '>I', lambda s: len(s.table) if s.size == 0 else 0),
    ListField('table', '>I', times=lambda ctx: ctx['nitems'] if ctx['size'] == 0 else 0)
  ]


class stsc(Struct):  # Sample-to-Chunk Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('nitems?', '>I', lambda s: len(s.table)),
    ListField('table', '>III', times='nitems')
  ]


class stco(Struct):  # Chunk Offset Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('nitems?', '>I', lambda s: len(s.table)),
    ListField('table', '>I', times='nitems')
  ]


class stbl(Struct):  # Sample Table Atom
  # stsd stts ctts cslg stss stps stsc stsz stco stsh sgpd sbgp sdtp
  _fields_ = [
    SubAtomsField('atoms', [stts, stsd, stss, stsz, stsc, stco])
  ]


class data_reference(Struct):
  # It's actually we could parse as #SubAtomsList in the #dref, but all atom
  # types behave the same way.
  _fields_ = [
    Field('size?', '>I', lambda s: len(s.data) + 8),
    StringField('tag', length=4),
    Field('v', '>B'),
    Field('flags', '>3B'),
    StringField('data', length=lambda ctx: ctx['size']-4-8)
  ]


class dref(Struct):  # Data Reference Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('nitems?', '>I', lambda s: len(s.references)),
    ListField('references', data_reference, times='nitems')
  ]


class dinf(Struct):  # Data Information Atoms
  _fields_ = [
    SubAtomsField('refs', [dref])
  ]


class vmhd(Struct):  # Video Media Information Header Atom
  _fields_ = [
    Field('v', '>B'),
    Field('flags', '>3B'),
    Field('graphics_mode', '>H'),
    Field('opcolor', '>3H')
  ]


class minf(Struct):  # Media Info Atom
  # vmhd hdlr dinf stbl
  _fields_ = [
    SubAtomsField('atoms', [vmhd, hdlr, dinf, stbl])
  ]


class mdia(Struct):  # Media  Atom
  # mdhd elng hdlr minf udta
  _fields_ = [
    SubAtomsField('atoms', [mdhd, minf, hdlr])
  ]


class trak(Struct):  # Track Atom
  # prfl tkhd tapt clip matt edts tref txas load imap mdia udta
  _fields_ = [
    SubAtomsField('atoms', [tkhd, mdia])
  ]


class moov(Struct):  # Movie Atom
  # pfrl mvhd clip udta trak
  _fields_ = [
    SubAtomsField('atoms', [mvhd, trak])
  ]
