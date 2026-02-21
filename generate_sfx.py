import subprocess, os, sys

ff = rC:Usersjomg2AppDataLocalProgramsPythonPython310libsite-packagesimageio_ffmpegbinariesffmpeg-win-x86_64-v7.1.exe
base = rC:toolyousohrtsassetssfx

for d in [comedy, drama, transitions, reactions, korean]:
    os.makedirs(os.path.join(base, d), exist_ok=True)

commands = []

# 1. laugh.mp3
commands.append((comedy/laugh.mp3, [ff, -y,
    -f, lavfi, -i, sine=frequency=440:duration=1,
    -f, lavfi, -i, sine=frequency=587:duration=1,
    -f, lavfi, -i, sine=frequency=700:duration=1,
    -f, lavfi, -i, anoisesrc=d=1:c=pink:r=44100:a=0.08,
    -filter_complex, [0][1][2][3]amix=inputs=4:duration=shortest,tremolo=f=9:d=0.7,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.6:d=0.4,volume=2.0,
    -t, 1, -ar, 44100, -b:a, 192k]))

print(Script loaded)