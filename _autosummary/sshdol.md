# sshdol

SSH-based file access with Mapping interface.

Provides read-only (SshFilesReader) and read-write (SshFiles) implementations
for accessing remote files over SSH.

| read-only          | read-write         |
<br/>
:—– | :—————– | :—————– |
<br/>
bytes  | SshFilesReader     | SshFiles           |
<br/>
text   | SshTextFilesReader | SshTextFiles       |
<br/>

### Modules

| [`base`](sshdol.base.md#module-sshdol.base)   | Base functionality for sshdol.   |
|----------------------------------------------------------------------------|----------------------------------|
