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

from movio import MovAtomR
import collections
import struct


def _unpack_atoms(cls, data, collect_separately=()):
  kwargs = {k: None for k in cls._fields}
  separately = []
  for atom in MovAtomR.make_root(data).iter_atoms():
    name = atom.tag.decode('ascii', 'ignore')
    if name not in kwargs and name not in collect_separately:
      print('warning: unknown atom "{}" in "{}"'.format(name, cls.__name__))
      continue
    elif name in collect_separately:
      separately.append(atom.to_atomd())
    elif name in globals():  # TODO
      kwargs[name] = globals()[name].unpack(atom.read_data())
  if collect_separately:
    return kwargs, separately
  else:
    return cls(**kwargs)


class moov(collections.namedtuple('moov', 'pfrl mvhd clip udta tracks')):

  @classmethod
  def unpack(cls, data):
    kwargs, remainders = _unpack_atoms(cls, data, ['trak'])
    kwargs['tracks'] = []
    for atom in remainders:
      if atom.tag == b'trak':
        kwargs['tracks'].append(trak.unpack(atom.data))
    return cls(**kwargs)


class trak(collections.namedtuple('trak', 'prfl tkhd tapt clip matt edts tref txas load imap mdia udta')):

  @classmethod
  def unpack(cls, data):
    return _unpack_atoms(cls, data)


class tkhd(collections.namedtuple('tkhd', 'vf create_time mod_time track_id duration layer alternate_group volume matrix_structure track_width track_height')):

  @classmethod
  def unpack(cls, data):
    s = struct.Struct('>4I4xI8x3H2x')
    m = struct.Struct('>9I')
    t = struct.Struct('>2I')
    args = s.unpack(data[:s.size]) + (m.unpack(data[s.size:s.size+m.size]),) + t.unpack(data[s.size+m.size:])
    return cls(*args)


class mdia(collections.namedtuple('mdia', 'mdhd elng hdlr minf udta')):

  @classmethod
  def unpack(cls, data):
    return _unpack_atoms(cls, data)


class mdhd(collections.namedtuple('mdhd', 'vf create_time mod_time time_scale duration language quality')):

  @classmethod
  def unpack(cls, data):
    return cls(*struct.unpack('>5I2H', data))


# TODO: elng


class hdlr(collections.namedtuple('hdlr', 'vf comp_type comp_subtype comp_manf comp_flags comp_flags_mask comp_name')):

  @classmethod
  def unpack(cls, data):
    args = struct.unpack('>6I', data[:6*4])
    args += (data[6*4:],)
    return cls(*args)


class minf(collections.namedtuple('minf', 'vmhd hdlr dinf stbl')):

  @classmethod
  def unpack(cls, data):
    return _unpack_atoms(cls, data)


class dinf(collections.namedtuple('dinf', 'refs')):

  @classmethod
  def unpack(cls, data):
    refs = []
    for atom in MovAtomR.make_root(data).iter_atoms():
      if atom.tag != b'dref':
        print('warning: unexpected atom "{}" in "dinf"'.format(atom.tag.decode('ascii', 'ignore')))
      else:
        refs.append(dref.unpack(atom.read_data()))
    return cls(refs)


class dref(collections.namedtuple('dref', 'vf refs')):

  DataReference = collections.namedtuple('DataReference', 'tag vf data')

  @classmethod
  def unpack(cls, data):
    vf, nitems = struct.unpack('>II', data[:8])
    offset = 8
    items = []
    for i in range(nitems):
      size, vf = struct.unpack('>I4xI', data[offset:offset+12])
      tag = data[offset+4:offset+8]
      items.append(cls.DataReference(tag, vf, data[offset:offset+size]))
      offset += size
    return cls(vf, items)


class stbl(collections.namedtuple('stbl', 'stsd stts ctts cslg stss stps stsc stsz stco stsh sgpd sbgp sdtp')):

  @classmethod
  def unpack(cls, data):
    kwargs = {k: None for k in cls._fields}
    for atom in MovAtomR.make_root(data).iter_atoms():
      name = atom.tag.decode('ascii', 'ignore')
      if name not in kwargs:
        print('warning: unknown atom "{}" in "stbl"'.format(name))
        continue
      if name in globals():  # TODO
        kwargs[name] = globals()[name].unpack(atom.read_data())
    return cls(**kwargs)


class stsd(collections.namedtuple('stsd', 'vf desc')):

  SampleDescription = collections.namedtuple('SampleDescription', 'fmt dri data')

  @classmethod
  def unpack(cls, data):
    vf, nitems = struct.unpack('>II', data[:8])
    items = []
    offset = 8
    for _ in range(nitems):
      size = struct.unpack('>I', data[offset:offset+4])[0]
      di = struct.unpack('>H', data[offset+14:offset+16])[0]
      item = cls.SampleDescription(data[offset+4:offset+8], di, data[offset+16:offset+16+size])
      items.append(item)
      offset += size
    return cls(vf, items)


class stts(collections.namedtuple('stts', 'vf table')):

  @classmethod
  def unpack(cls, data):
    vf, nitems = struct.unpack('>II', data[:8])
    items = []
    for i in range(nitems):
      offset = 8 + i*8
      items.append(struct.unpack('>II', data[offset:offset+8]))
    return cls(vf, items)

  def pack(self):
    head = struct.pack('>II', self.vf, len(self.table))
    for item in self.table:
      head += struct.pack('>II', *item)
    return head


class stss(collections.namedtuple('stss', 'vf table')):

  @classmethod
  def unpack(cls, data):
    vf, nitems = struct.unpack('>II', data[:8])
    items = []
    for i in range(nitems):
      offset = 8 + i*4
      items.append(struct.unpack('>I', data[offset:offset+4])[0])
    return cls(vf, items)


class stsz(collections.namedtuple('stsz', 'vf size table')):

  @classmethod
  def unpack(cls, data):
    vf, size, nitems = struct.unpack('>III', data[:12])
    items = []
    if size == 0:
      for i in range(nitems):
        offset = 12 + 4*i
        items.append(struct.unpack('>I', data[offset:offset+4])[0])
    return cls(vf, size, items)

  def pack(self):
    data = struct.pack('>III', self.vf, self.size, len(self.table))
    for item in self.table:
      data += struct.pack('>I', item)
    return data


class stsc(collections.namedtuple('stsc', 'vf table')):

  @classmethod
  def unpack(cls, data):
    vf, nitems = struct.unpack('>II', data[:8])
    items = []
    for i in range(nitems):
      offset = 8 + i*12
      items.append(struct.unpack('>III', data[offset:offset+12]))
    return cls(vf, items)

  def pack(self):
    data = struct.pack('>II', self.vf, len(self.table))
    for item in self.table:
      data += struct.pack('>III', *item)
    return data


class stco(collections.namedtuple('stco', 'vf table')):

  @classmethod
  def unpack(cls, data):
    vf, nitems = struct.unpack('>II', data[:8])
    items = []
    for i in range(nitems):
      offset = 8 + i*4
      items.append(struct.unpack('>I', data[offset:offset+4])[0])
    return cls(vf, items)

  def pack(self):
    data = struct.pack('>II', self.vf, len(self.table))
    for item in self.table:
      data += struct.pack('>I', item)
    return data
