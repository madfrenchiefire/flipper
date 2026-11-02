# Original iShow II content

Copy these folders from the unpacked iShow II (`C:\iShowII_EN`) into this folder:

| Folder | What it is | Used by the app |
|---|---|---|
| `ILDAimage` | 476 standard `.ild` laser shows and pictures | **Yes**: linked automatically as a library section |
| `Quickframe` (with `A`, `B`, `C` inside) | iShow's "quick frame" pads (`.ilf`) | Planned (importer needs a sample file) |
| `Frames` | More `.ilf` animations | Planned |
| `Drawing` | iShow's drawing library (`.ddr`) | Planned |
| `Effect`, `EffectLIST` | Movement effects (rotate, bounce, ...) | Planned |
| `Section`, `Sequence` | Show programming | Planned |

Not needed: `Music` (MP3s), `DrivesII` (32-bit drivers that can't load on Windows 11), and
`iShowII_En.exe`, `iShow.ini` and `start1.bmp`.

When the app starts it looks here (and in `C:\iShowII_EN`) and adds `ILDAimage` to the library on
its own. If you remove the folder in the app, it stays removed.
