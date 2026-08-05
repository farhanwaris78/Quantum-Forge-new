# QuantumForge Research Tutorial: Advanced Atomistic Modeling & DFT

## 1. Introduction
QuantumForge is a professional graphical user interface (GUI) designed to accelerate materials discovery using Quantum ESPRESSO, VASP, and other first-principles software. This tutorial covers advanced workflows from 2D materials to AI-accelerated simulations.

---

## 2. Twistronics & 2D Materials
### 2.1 Building Moiré Supercells
Twisted Bilayer Graphene (TBG) and other twisted van der Waals heterostructures exhibit exotic physics like flat bands and superconductivity.
1. Open the **Modeler** tab.
2. Select **Moiré Pattern Builder**.
3. Load two monolayer structures.
4. Specify the **Twist Angle** (e.g., 1.1° for "magic angle" graphene).
5. Click **Build commensurate cell**.

### 2.2 Janus Layers & Surface Physics
For materials like MoSSe with broken mirror symmetry:
1. Use the **Janus Layer Builder** to replace the top chalcogen layer with a different element.
2. Navigate to the **Isolated System (2D)** tab.
3. Enable **ESM (Effective Screening Medium)** and **Dipole Correction** to calculate accurate work functions.

---

## 3. High-Impact Physical Properties
### 3.1 Phonon Stability (No Negative Frequencies)
Imaginary frequencies (plotted as negative values) indicate an unstable structure.
1. Optimize your structure using `vc-relax` with tight convergence (`forc_conv_thr = 1d-4`).
2. Use the **Jiggle** tool in the Modeler to break symmetry and test for global minima.
3. In the **Phonon** tab, ensure **ASR = 'crystal'** is selected.

### 3.2 Elasticity & ELATE
1. Run a `thermo_pw` calculation.
2. Open the **Elasticity** result tab.
3. QuantumForge will plot Young's Modulus and Poisson's ratio as directional "balloons" or cross-sectional plots.

---

## 4. AI & Machine Learning Workflows
### 4.1 Parameter Optimization
1. Use the **AI Assistant** in the SCF tab.
2. Click **Suggest Cutoffs**; QuantumForge uses elemental hardness rules to recommend `ecutwfc` and `ecutrho`.

### 4.2 Machine Learning Potentials (MLP)
1. Run a Molecular Dynamics (MD) job.
2. Go to **Result Explorer** and select **MLP Export**.
3. Export the trajectory in **Extended XYZ** format for training **DeepMD-kit** or **MACE** models.

---

## 5. Battery Research & Ion Transport
1. Build an electrode-electrolyte interface in the **Modeler**.
2. Use the **Battery Workbench** to generate Nudged Elastic Band (NEB) paths for ion hopping.
3. Visualize the **Voltage Profile** and **Ion Activation Map** to predict battery performance.

---

## 6. Spectroscopy
### 6.1 IR, Raman, and NMR
1. Set up your calculation in the **Spectroscopy** wizard.
2. QuantumForge automates the execution of `ph.x` and `gipaw.x`.
3. Results are plotted with Lorentzian broadening for direct comparison with experimental data.
