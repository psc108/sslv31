lines = open('src/components/jar-analyser/SubReportView.tsx', encoding='utf-8').readlines()
for i in range(375, 392):
    print(i+1, repr(lines[i]))
