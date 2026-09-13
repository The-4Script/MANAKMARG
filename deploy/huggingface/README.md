---
title: MANAK MARG
colorFrom: yellow
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# MANAK MARG

This Space runs the MANAK MARG FastAPI application and its built React frontend.

The Docker image restores the committed runtime data bundle during the image build. If the bundle is stored
outside the Space repository, set `MANAKMARG_DATA_URL` in the Space settings instead.

Keep the Space private unless redistribution of the bundled BIS-derived data has been reviewed. The app has no
authentication and uploaded documents are temporary; do not use it for confidential documents.