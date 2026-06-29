# Fancy searchts demo recorder: vhs (ttyd + ffmpeg) + python + searchts
FROM ghcr.io/charmbracelet/vhs

USER root

# Python + a crisp mono font for the recording
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pip ca-certificates fonts-jetbrains-mono \
 && rm -rf /var/lib/apt/lists/*

# Install searchts from PyPI (curl_cffi tier + keyless search are enough for the demo)
RUN pip3 install --no-cache-dir --break-system-packages searchts

# A clean, branded prompt for the recording
RUN printf '%s\n' "PS1='\[\e[38;5;212m\]capad\[\e[0m\] \[\e[38;5;117m\]~\[\e[0m\] $ '" >> /root/.bashrc
