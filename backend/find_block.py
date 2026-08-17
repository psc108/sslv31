lines = open('app/services/jar_analyser/job.py', encoding='utf-8').readlines()
for i, line in enumerate(lines):
    if 'frontend_installer' in line or 'no Java content' in line or '# Dependencies' in line:
        print(i+1, repr(line))
