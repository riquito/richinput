Richinput
=========

Richinput is a library to read one character at a time from standard input in
a nonblocking way.

As a key is pressed a callback is invoked, without waiting for <Return>.

Encodings are respected (the read char is unicode) and there are functions to
deal with terminal escape sequences.

It is possible to read input one character at a time maintaining arrows keys,
home key, end key, backspace and word wrap working normally.

API
---

### get_char(prompt=u'')

Iterator that reads one character at a time, nonblocking, encoding aware. 
Yield a unicode character.

It is a low-level function, unless you want to decode terminal escape 
sequences yourself, use `get_rich_char` instead.

### get_rich_char(prompt=u'', term=None)

Iterator that reads one "meaningful value" at a time, nonblocking, encoding 
aware.
`prompt` is a label displayed before reading the input.
`term` is an instance of terminfo.Term, needed to understand what the escape
sequences means. If set to None it will be automatically detected.


The yielded value will be one of
- PrintableChar, if the character was not in a unicode General_Category starting
  with C.
- ControlKey, if the character was in a unicode General_Category starting with C
- EscapeSequence, if a terminal escape sequence was detected (e.g. a colour 
  formatting request or the home key).

Note that only `PrintableChar` has a non-empty string representation, so 
something like the following code may come in handy

    >>> print(''.join(get_rich_char(term)))

### Richline

Use this class if you want the user to be able to have richline like capabilities
(cursor movements, home/end keys, backspace, etc.) and still be notified at each
key press.
   
    def my_callback(cb, key_event, *args):
        if isinstance(key_event, PrintableChar):
            # do something, e.g. log the current letter
            log(key_event.value)

        return cb(None, key_event, *args)

    richline = Richline()
    text = richline.read(cb=my_callback)

You may modify the input, but either modify one readable character at a time or
be in for a lot of pain.

This example colour the input and automatically change to uppercase the 
readable characters:

    color_idx = 1
    def colorful_string(cb, *args):
        global color_idx
        sys.stdout.write('\033[1;%dm' % ((color_idx % 8) + 30))
        color_idx += 1

        res = cb(None, *args)
        sys.stdout.write('\033[0m')
        return res

    def up(cb, key_event, term, vterm, iline, previous, current, prev_idx, next_idx):
        if isinstance(key_event, PrintableChar):
            key_event.value = key_event.value.upper()
            current = current[:-1] + key_event.value
            iline.text = current
            log(current, previous)

        return colorful_string(cb, key_event, term, vterm, iline, previous, current, prev_idx, next_idx)

    richline = RichLine()
    text = richline.read(cb=up, prompt='Write what you want, try home key, arrows, canc, word-wrap,...: ')
    print('\nYou wrote: ' + text)

### RichPassword

Read a password displaying asterisks each time a key is pressed, showing for a
second the latest typed character and letting the user move with arrows.
If you press F1 you can toggle the asterisks on/off.

    pw = RichPassword().read(prompt='Password: ')

License
=======

Copyright 2014 Riccardo Attilio Galli <riccardo@sideralis.org> [http://www.sideralis.org]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.