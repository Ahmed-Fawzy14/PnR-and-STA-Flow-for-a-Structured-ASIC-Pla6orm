# PnR and STA Flow for a Structured ASIC Platform

A Python-based toolset for Place and Route (PnR) and Static Timing Analysis (STA) workflows targeting structured ASIC platforms. This project provides automated pin placement parsing, visualization, and validation capabilities for ASIC design flows.

## 📋 Overview

This repository implements a comprehensive flow for handling pin placement configurations in structured ASIC designs. The toolset parses YAML-based pin placement specifications and converts them into structured formats suitable for downstream EDA tools and visualization.


## 📁 Repository Structure

```
.
├── pins_parser.py          # Main pin placement parser module
├── src/                    # Source code directory
├── designs/                # Design files and configurations
├── data/                   # Data files and input specifications
├── docs/                   # Documentation
├── build/                  # Build outputs and generated files
└── REAME.md               # Project documentation
```

## 🔧 Installation

### Prerequisites

- Python 3.6 or higher
- PyYAML library

### Setup

```bash
# Clone the repository
git clone https://github.com/Ahmed-Fawzy14/PnR-and-STA-Flow-for-a-Structured-ASIC-Pla6orm.git
cd PnR-and-STA-Flow-for-a-Structured-ASIC-Pla6orm

# Install dependencies
pip install pyyaml
```
