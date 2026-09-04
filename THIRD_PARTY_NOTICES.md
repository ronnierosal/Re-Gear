# Third-party notices

HDM was designed using validated behavior and engineering lessons from the
MIT-licensed eGPUBridge project:

- Source: https://github.com/ronnierosal/eGPUBridge
- Frozen reference commit: `ef04f65f1d35887ada69ef6a11807e6db0ae1c0d`
- Original copyright: Copyright (c) 2026 Vova + GPT

The root-to-user systemd query design was informed by the frozen reference's
validated SteamOS behavior. No eGPUBridge source file was copied into this
repository. If a later change copies or substantially derives implementation
code, the relevant MIT copyright and permission notice must accompany that
portion.

## Gamescope performance protocol

The original Python read-only wire client implements the private
`gamescope_control` v6 protocol. Protocol names, signatures and opcode ordering
were derived from Valve's protocol description at Gamescope revision
`3521d6bf058110ea09198db9e5ca87f395c25b9e`:
https://github.com/ValveSoftware/gamescope/blob/3521d6bf058110ea09198db9e5ca87f395c25b9e/protocol/gamescope-control.xml

The protocol description carries this notice:

Copyright © 2023 Valve Corporation

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice (including the next
paragraph) shall be included in all copies or substantial portions of the
Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
