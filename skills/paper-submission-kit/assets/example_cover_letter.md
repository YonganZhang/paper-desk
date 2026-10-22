---
# Fictitious example: a complete cover letter built from cover_letter.md for an invented paper and journal.
# Borrow its structure and sentence patterns only; every fact in a real letter comes from that paper.
# Render: python3 ../scripts/render_cover_letter.py example_cover_letter.md <out dir> --roster authors.example.yml
title: "Physics-guided graph learning for short-term water demand forecasting across district metered areas"
authors: [San Zhang, Alice Li, Si Li]
journal: Example Journal of Water Systems
closing: "Sincerely,"
signers: [li-si, zhang-san]
---

Dear Editor,

We respectfully submit our manuscript, "Physics-guided graph learning for short-term water demand forecasting across district metered areas", for consideration as a Research Article in *Example Journal of Water Systems*.

Short-term demand forecasts decide how utilities schedule pumps and detect leaks, and forecast errors translate directly into energy waste and late leak alarms. Yet forecasting demand for many district metered areas at once faces a persistent challenge. Statistical models per area are transparent but ignore how neighbouring areas share pressure and supply, whereas deep sequence models capture complex patterns but need long, clean records that most areas lack. How much accuracy is lost by treating areas in isolation, and where network coupling matters most, has therefore remained unknown. This study addresses this gap with a physics-guided graph network (PG-Net).

PG-Net represents areas as nodes connected through the pipe network and constrains its predictions with a mass-balance term at each supply inlet. It is evaluated on 120 metered areas of three fictitious utilities over two years of hourly data.

The manuscript makes four principal contributions.

**A forecasting method that respects network mass balance.** PG-Net couples graph message passing with an inlet mass-balance penalty, so area forecasts add up to the measured supply. It reduces the mean absolute percentage error from 9.4% to 6.1% against the best per-area baseline, and repeat training runs differ by less than 0.2 percentage points.

**Coupling matters most in small and data-poor areas.** The accuracy gain is largest in areas with fewer than six months of records, where errors fall by 41%, showing that neighbours supply the information that short records lack.

**Forecast errors as an early leak signal.** Persistent positive residuals of PG-Net precede 17 of 21 confirmed leak events by a median of 26 hours, two to three times earlier than night-flow analysis.

**Guidance for meter placement.** Ranking areas by how much their forecasts depend on neighbours identifies where one additional meter improves network-wide accuracy most, giving utilities a basis for staged metering investment.

The manuscript is closely aligned with the scope of *Example Journal of Water Systems* through its integration of urban water networks, machine learning and operational decision support. Beyond reporting a more accurate model, the study shows when and where network coupling should be modelled, and how forecasts can serve leak detection. All code and the anonymised data are openly available.

We affirm that this manuscript reports original work that has not been published and is not under consideration elsewhere. All authors have reviewed and approved the manuscript and declare no competing interests. Funding, data availability and code availability are fully disclosed in the manuscript.
