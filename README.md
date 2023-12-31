# MRE-PINN

This repository contains code for the paper *Physics-informed neural networks for tissue elasticity reconstruction in magnetic resonance elastography* which is to be presented at MICCAI 2023.

![MRE-PINN examples](MICCAI-2023/images/patient_image_grid.png)

## Installation

Run the following to setup the conda environment and register it as a Jupyter notebook kernel:

```bash
mamba env create --file=environment.yml
mamba activate MRE-PINN
python -m ipykernel install --user --name=MRE-PINN
```

## Usage

This [notebook](MICCAI-2023/MICCAI-2023-simulation-training.ipynb) downloads the BIOQIC simulation data set and trains PINNs to reconstruct a map of shear elasticity from the displacement field.

The notebook takes roughly 2.5 h to train for 100,000 iterations on an RTX 5000 and uses 2.5 GiB of GPU memory.
