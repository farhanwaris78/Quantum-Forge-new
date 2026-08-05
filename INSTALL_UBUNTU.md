# Installing QuantumForge on Ubuntu

The complete multi-platform tutorial (Ubuntu 20.04→current, Arch, Windows, macOS,
safe update/uninstall, MobaXterm) is:

**[`docs/TUTORIAL_INSTALL.md`](docs/TUTORIAL_INSTALL.md)**

Concise Ubuntu section also lives in:

**[`docs/INSTALLATION.md`](docs/INSTALLATION.md#4-ubuntu-2004-and-later)**

## Quick portable install

```bash
sudo apt update
sudo apt install openjdk-17-jre curl python3 xauth libgtk-3-0 libxtst6 libxrender1 libxi6

# After downloading and verifying SHA256SUMS for the release asset:
tar -xzf QuantumForge-2.0.0-linux-x64.tar.gz
cd QuantumForge-2.0.0-linux-x64
./install.sh
export PATH="$HOME/.local/bin:$PATH"

quantumforge --doctor
quantumforge
```

## Update / uninstall

```bash
quantumforge --update
quantumforge --uninstall          # keeps ~/.quantumforge
quantumforge --uninstall --purge  # also deletes user data after confirmation
```

For Quantum ESPRESSO, thermo_pw, phonopy, BoltzTraP2, XCrySDen, VASP/CASTEP status,
LAMMPS and ML-potential environments, read
[`docs/SCIENTIFIC_SOFTWARE_GUIDE.md`](docs/SCIENTIFIC_SOFTWARE_GUIDE.md).

Do not use the historical instruction to run a nonexistent `quantumforge.sh` or
assume QE executables are bundled. Release 2.0.0 does not bundle external
calculation engines.
