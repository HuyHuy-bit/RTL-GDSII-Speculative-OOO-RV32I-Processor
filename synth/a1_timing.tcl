read_liberty $liberty
read_verilog $netlist
link_design $top
read_sdc $constraints

check_setup -verbose > $reports/coverage.rpt
report_checks -path_delay max -group_count 10 -fields {slew capacitance input_pin net} -digits 4 > $reports/setup.rpt
report_checks -path_delay min -group_count 10 -fields {slew capacitance input_pin net} -digits 4 > $reports/hold.rpt
report_checks -unconstrained -path_delay max -group_count 100 -digits 4 > $reports/paths_including_unconstrained.rpt
report_check_types -all_violators -max_delay -min_delay -format end -digits 4 > $reports/setup_hold_violations.rpt
report_check_types -all_violators -max_transition -digits 4 > $reports/slew_violations.rpt
report_worst_slack -digits 6 > $reports/worst_slack.rpt
report_tns -digits 6 > $reports/tns.rpt
if {$top eq "a1_backend_probe"} {
    report_checks -to [get_ports {read_data_o*}] -path_delay max -group_count 3 -digits 4 > $reports/read_data.rpt
    report_checks -from [get_ports {wb_addr_i*}] -to [get_ports {read_data_o*}] -path_delay max -group_count 3 -digits 4 > $reports/wakeup_read.rpt
}
puts "A1 STA COMPLETE"
