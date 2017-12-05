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

import io
import struct
import sys


def with_metaclass(meta, *bases):
  """Create a base class with a metaclass."""
  return meta("NewBase", bases, {})


class InitSubclassMeta(type):
  """
  Adds support for `__init_subclass__()` to classes before Python version 3.6.
  """

  # PEP 487 introduces __init_subclass__() in Python 3.6
  if sys.version < '3.6':
    def __new__(cls, name, bases, data):
      if '__init_subclass__' in data:
        data['__init_subclass__'] = classmethod(data['__init_subclass__'])
      sub_class = super(InitSubclassMeta, cls).__new__(cls, name, bases, data)
      sub_super = super(sub_class, sub_class)
      if hasattr(sub_super, '__init_subclass__'):
        sub_super.__init_subclass__()
      return sub_class


class UnpackError(Exception):
  pass


class PackError(Exception):
  pass


class UnpackContext(object):
  """
  Context structure used during the unpacking of structs.
  """

  def __init__(self, struct_type, parent=None):
    self.struct_type = struct_type
    self.field_values = {}
    self.init_values = {}
    self.parent = parent

  def __getitem__(self, key):
    return self.field_values[key]


class Field(object):
  """
  Represents a field in a C-structure. Fields can be implicit, in which case
  their value will be used in the context of unpacking other fields in the
  same struct and later be derived from another field when packing.
  """

  def __init__(self, name, fmt, getter=None, hidden=False):
    if name.endswith('?'):
      name = name[:-1]
      hidden = True
    if (hidden and name) and not getter:
      raise ValueError('named hidden field requires a getter')
    elif not (hidden and name) and getter:
      raise ValueError('getter can only be used for named hidden fields')
    self.name = name
    self.fmt = fmt
    self.getter = getter
    self.hidden = hidden
    if not self.wraps_struct() and self.fmt is not None:
      try:
        self.fmt = struct.Struct(self.fmt)
      except struct.error as e:
        raise struct.error('{} ({!r})'.format(e, self.fmt))

  def __eq__(self, other):
    if isinstance(other, Field):
      if self.name != other.name:
        return False
      if self.wraps_struct():
        if other.fmt is not self.fmt:
          return False
      else:
        if other.wraps_struct():
          return False
        if self.fmt.format != other.fmt.format:
          return False
      return True
    return False

  def wraps_struct(self):
    return isinstance(self.fmt, type) and issubclass(self.fmt, Struct)

  def size(self):
    if self.wraps_struct():
      return self.fmt._struct_size_
    else:
      return self.fmt.size

  def unpack_from_stream(self, ctx, fp):
    if self.wraps_struct():
      return self.fmt.unpack_from_stream(fp, UnpackContext(self.fmt, ctx))
    else:
      data = fp.read(self.fmt.size)
      try:
        value = self.fmt.unpack(data)
      except struct.error as e:
        raise UnpackError('field {}.{} (got {} bytes): {}'.format(
            ctx.struct_type.__name__, self.name, len(data), e))
      if len(value) == 1:
        value = value[0]
      return value

  def pack_into_stream(self, struct_type, fp, value):
    if self.wraps_struct():
      assert isinstance(value, self.fmt), (type(value), self.fmt)
      value.pack_into_stream(fp)
    else:
      if value is None:
        value = ()
      elif not isinstance(value, tuple):
        value = (value,)
      try:
        fp.write(self.fmt.pack(*value))
      except struct.error as e:
        raise PackError('field {}.{}: {}'.format(
            struct_type.__name__, self.name, e))


class ListField(Field):
  """
  Represents a list of items that is repeated either a fixed number of times
  or based on the value of another field.
  """

  def __init__(self, name, fmt, times):
    super(ListField, self).__init__(name, fmt)
    self.times = times

  def size(self):
    return None

  def unpack_from_stream(self, ctx, fp):
    if isinstance(self.times, str):
      times = ctx.field_values[self.times]
    elif callable(self.times):
      times = self.times(ctx)
    else:
      times = self.times
    values = []
    for i in range(times):
      values.append(super(ListField, self).unpack_from_stream(ctx, fp))
    return values

  def pack_into_stream(self, struct_type, fp, items):
    for value in items:
      super(ListField, self).pack_into_stream(struct_type, fp, value)


class StringField(Field):

  def __init__(self, name, length):
    super(StringField, self).__init__(name, None)
    self.length = length

  def size(self):
    return None

  def unpack_from_stream(self, ctx, fp):
    if isinstance(self.length, str):
      length = ctx.field_values[self.length]
    elif callable(self.length):
      length = self.length(ctx)
    else:
      length = self.length
    data = fp.read(length)
    if len(data) != length:
      raise UnpackError('{}.{} expected {} bytes (got {})'.format(
          ctx.struct_type.__name__, self.name, length, len(data)))
    return data

  def pack_into_stream(self, struct_type, fp, data):
    fp.write(data)


class Struct(with_metaclass(InitSubclassMeta)):
  """
  Represents a C-structure that constist of #_Field#s.
  """

  # _fields_
  # _fields_map_
  # _visible_fields_
  # _struct_size_

  def __init_subclass__(cls, **kwargs):
    cls._fields_map_ = {}
    cls._visible_fields_ = []
    struct_size = 0
    for field in cls._fields_:
      if not field.hidden and field.name:
        cls._visible_fields_.append(field)
      if field.name:
        cls._fields_map_[field.name] = field
      if struct_size is not None:
        field_size = field.size()
        if field_size is None:
          struct_size = None
        else:
          struct_size += field_size
    cls._struct_size_ = struct_size

  def __init__(self, *args, **kwargs):
    if len(args) > len(self._visible_fields_):
      raise TypeError('{}() expects at most {} positional arguments'.format(
          type(self).__name__, len(self._visible_fields_)))
    for field, arg in zip(self._visible_fields_, args):
      if field.name in kwargs:
        raise TypeError('{}() argument "{}" specified twice'.format(
            type(self).__name__, field.name))
      kwargs[field.name] = arg
    for field in self._visible_fields_:
      if field.name not in kwargs:
        raise TypeError('{}() missing argument "{}"'.format(
            type(self).__name__, field.name))
    vars(self).update(kwargs)

  def __repr__(self):
    attrs = ((k.name, getattr(self, k.name)) for k in self._fields_ if k.name)
    attrs = ('{}={!r}'.format(k, v) for k, v in attrs)
    return '{}({})'.format(type(self).__name__, ', '.join(attrs))

  def __getattr__(self, name):
    field = self._fields_map_.get(name)
    if field is not None and field.hidden:
      assert field.getter, 'named hidden field has not getter'
      return field.getter(self)
    raise AttributeError(name)

  def __setattr__(self, name, value):
    field = self._fields_map_.get(name)
    if field is None or field.hidden:
      raise AttributeError('can not set attribute {}.{}'.format(
          type(self).__name__, name))
    super(Struct, self).__setattr__(name, value)

  def __eq__(self, other):
    if isinstance(other, Struct) and len(self._fields_) == len(other._fields_):
      for fa, fb in zip(self._fields_, other._fields_):
        if fa != fb:
          return False
        if fa.name and (not fa.hidden or fa.getter):
          if getattr(self, fa.name) != getattr(other, fa.name):
            return False
      return True
    return False

  def asdict(self, deep=False, cnv_keys=('asdict', '_asdict')):
    result = {f.name: getattr(self, f.name) for f in self._visible_fields_}
    if deep:
      for key, value in result.items():
        for x in cnv_keys:
          if hasattr(value, x):
            result[key] = getattr(value, x)()
            break
    return result

  def pretty_print(self, fp=None, indent='  ', depth=0):
    if fp is None:
      fp = sys.stdout
    fp.write('{}(\n'.format(type(self).__name__))
    for field_index, field in enumerate(self._fields_):
      if not field.name: continue
      fp.write(indent * (depth+1) + '{}='.format(field.name))
      value = getattr(self, field.name)
      if isinstance(value, Struct):
        value.pretty_print(fp, indent, depth+1)
      elif isinstance(value, list):
        fp.write('[\n')
        for i, item in enumerate(value):
          fp.write(indent * (depth+2))
          if isinstance(item, Struct):
            item.pretty_print(fp, indent, depth+2)
          else:
            fp.write(repr(item))
          if i != len(value)-1:
            fp.write(',')
          fp.write('\n')
        fp.write(indent * (depth+1) + ']')
      else:
        fp.write('{!r}'.format(value))
      if field_index != len(self._fields_)-1:
        fp.write(',')
      fp.write('\n')
    fp.write(indent * depth + ')')
    if depth == 0:
      fp.write('\n')

  @classmethod
  def unpack_from_stream(cls, fp, ctx=None):
    if ctx is None:
      ctx = UnpackContext(cls)
    for field in cls._fields_:
      value = field.unpack_from_stream(ctx, fp)
      ctx.field_values[field.name] = value
      if not field.hidden:
        ctx.init_values[field.name] = value
    return cls(**ctx.init_values)

  @classmethod
  def unpack(cls, data, ctx=None):
    return cls.unpack_from_stream(io.BytesIO(data), ctx)

  def pack_into_stream(self, fp):
    for field in self._fields_:
      if field.name:
        value = getattr(self, field.name)
      else:
        value = None
      field.pack_into_stream(type(self), fp, value)

  def pack(self):
    fp = io.BytesIO()
    self.pack_into_stream(fp)
    return fp.getvalue()
