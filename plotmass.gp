set title "Mass Deficiency"
set datafile separator ","
#set xrange [:]
#set yrange [:]

# Atommassen in der CSV -> Masse des H-1-Atoms (Proton + Elektron) verwenden, nicht die Protonenmasse
hydrogen = 1.00782503223
#proton = 1.007276
neutron = 1.008664

#hydrogen = 1
#neutron = 1

#set xlabel "Amount of Nucleons [p+n]"
set xlabel "Proton Number"
#set ylabel "Massdifference/Nuc [u]"
#set ylabel "Nucleons - Mass [Du]"
set ylabel "Difference to Single Nucleons [du]"

set grid

#plot "nuclide_masses.csv" using ($2+$3):4 with linespoints
#plot "nuclide_masses.csv" using ($2+$3):(($2*neutron+$3*hydrogen)-$4)/($2+$3) with linespoints title "Energy/Nucleon"
plot "nuclide_masses.csv" using ($3):(($2*neutron+$3*hydrogen)-$4) with linespoints title "Mass Difference"
