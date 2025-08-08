
# redeploy trigger
from flask import Flask, render_template, request, send_file, jsonify, redirect, url_for
from pulp import *
import math
from datetime import datetime
import subprocess
import os
import io
import tempfile
import traceback
from jinja2 import Environment, FileSystemLoader, select_autoescape, StrictUndefined
import pytz
from dotenv import load_dotenv
import yfinance as yf
import logging

logging.getLogger('werkzeug').setLevel(logging.ERROR)

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Configuration ---
if os.environ.get("RENDER"):
    BASE_PATH = "/tmp"
else:
    BASE_PATH = "."

RESULT_FILE_NAME = os.path.join(BASE_PATH, "result1.txt")
RANGE_REPORT_FILE_NAME = os.path.join(BASE_PATH, "result2.txt")
INFEASIBILITY_FILE_NAME = os.path.join(BASE_PATH, "infeasibility_analysis.txt")
MOD_FILE = os.path.join(BASE_PATH, "model.mod")
DAT_FILE = os.path.join(BASE_PATH, "data.dat")
GLPSOL_PATH = None

# --- GLOBAL CONSTANTS ---
ALL_PROPERTIES = ["SPG", "SUL", "RON", "MON", "RVP", "E70", "E10", "E15", "ARO", "BEN", "OXY", "OLEFIN", "ETH"]
DISPLAY_PROPERTIES_LIST = ["SPG", "SUL", "RON", "ROI", "MON", "MOI", "RVP", "RVI", "E70", "E10", "E15", "ARO", "BEN", "OXY", "OLEFIN", "ETH"]
INTERNAL_PROPERTIES_LIST = ["SPG", "SUL", "RON", "ROI", "MON", "MOI", "RVP", "RVI", "E70", "E10", "E15", "ARO", "BEN", "OXY", "OLEFIN", "ETH"]

COMPONENT_HTML_KEYS = ["C4B", "IS1", "RFL", "F5X", "RCG", "IC4", "HBY", "AKK", "ETH", "LTN"]
COMPONENT_DISPLAY_NAMES = {
    "C4B": "Alkyl Butane", "IS1": "Isomerate", "RFL": "Reformate", "F5X": "Mixed RFC", "RCG": "FCC Gasoline",
    "IC4": "DIB IC4", "HBY": "SHIP C4", "AKK": "Alkylate", "ETH": "Ethanol", "LTN": "Light Naptha"
}

GRADE_NAMES = ["Regular", "Premium", "Super Premium"]
HARD_CONSTRAINTS = ['BEN', 'SUL','RON','ROI','MON','MOI','RVP','RVI','OXY','E10']
SOFT_CONSTRAINT_PENALTIES = {
     'OLEFIN':100, 'ARO': 20000, 'SPG': 300, 'E70': 1500000,'E15': 15000, 'ETH': 250,       
}

# --- Helper Functions ---
def calculate_roi(ron):
    """Calculate ROI from RON using the given formula"""
    return ron + 11.5 if ron < 85 else math.exp((0.0135 * ron) + 3.42)

def calculate_moi(mon):
    """Calculate MOI from MON using the given formula"""
    return mon + 11.5 if mon < 85 else math.exp((0.0135 * mon) + 3.42)

def calculate_rvi(rvp):
    """Calculate RVI from RVP using the given formula"""
    return (rvp * 14.5) ** 1.25

def reverse_roi_to_ron(roi):
    """Convert ROI back to RON"""
    return roi - 11.5 if roi <= 96.5 else (math.log(roi) - 3.42) / 0.0135

def reverse_moi_to_mon(moi):
    """Convert MOI back to MON"""
    return moi - 11.5 if moi <= 96.5 else (math.log(moi) - 3.42) / 0.0135

def reverse_rvi_to_rvp(rvi):
    """Convert RVI back to RVP"""
    return (rvi ** (1/1.25)) / 14.5

def get_display_property_info(prop, value):
    """Convert internal property values to display values for reporting."""
    conversions = {'ROI': ('RON', reverse_roi_to_ron), 'MOI': ('MON', reverse_moi_to_mon), 'RVI': ('RVP', reverse_rvi_to_rvp)}
    if prop in conversions:
        display_prop, converter = conversions[prop]
        return display_prop, converter(value)
    return prop, value

def convert_component_properties(components_data):
    """Convert component properties from RVP/MON/RON to RVI/MOI/ROI"""
    for comp in components_data:
        properties = comp['properties']
        if 'RON' in properties:
            properties['ROI'] = calculate_roi(properties['RON'])
        if 'MON' in properties:
            properties['MOI'] = calculate_moi(properties['MON'])
        if 'RVP' in properties:
            properties['RVI'] = calculate_rvi(properties['RVP'])
    return components_data

def convert_specs_to_internal(specs_data):
    """Convert specification bounds from RVP/MON/RON to RVI/MOI/ROI"""
    converted_specs = specs_data.copy()
    conversions = {
        'RON': ('ROI', calculate_roi),
        'MON': ('MOI', calculate_moi), 
        'RVP': ('RVI', calculate_rvi)
    }
    
    for ext_prop, (int_prop, converter) in conversions.items():
        if ext_prop in specs_data:
            converted_specs[int_prop] = {}
            for grade, bounds in specs_data[ext_prop].items():
                min_val = converter(bounds['min']) if bounds['min'] != 0 and not math.isinf(bounds['min']) else bounds['min']
                max_val = converter(bounds['max']) if not math.isinf(bounds['max']) else bounds['max']
                converted_specs[int_prop][grade] = {'min': min_val, 'max': max_val}
    return converted_specs

def check_violations(blend_data, components, property_values, spec_bounds, grade_name, properties_list):
    """Check constraint violations for a given blend - consolidated violation checking logic"""
    violations = {}
    total_vol = sum(blend_data[comp] for comp in components)
    if total_vol <= 0:
        return violations
        
    TOLERANCE = 1e-6
    
    for prop in properties_list:
        if prop in ['RON', 'MON', 'RVP']:  # Skip external properties
            continue
            
        min_val, max_val = spec_bounds.get((prop, grade_name), (0.0, float('inf')))
        
        # Calculate achieved value and get display representation
        if prop in ['ROI', 'MOI', 'RVI']:
            weighted_sum = sum(property_values.get((prop, comp), 0) * blend_data[comp] for comp in components)
            internal_achieved = weighted_sum / total_vol
            
            conversion_map = {'ROI': ('RON', reverse_roi_to_ron), 'MOI': ('MON', reverse_moi_to_mon), 'RVI': ('RVP', reverse_rvi_to_rvp)}
            display_prop, converter = conversion_map[prop]
            achieved_val = converter(internal_achieved)
            check_min = converter(min_val) if min_val is not None and not math.isinf(min_val) and min_val > 0 else None
            check_max = converter(max_val) if max_val is not None and not math.isinf(max_val) else None
        else:
            weighted_sum = sum(property_values.get((prop, comp), 0) * blend_data[comp] for comp in components)
            achieved_val = weighted_sum / total_vol
            display_prop = prop
            check_min = min_val if min_val is not None and not math.isinf(min_val) and min_val > 0 else None
            check_max = max_val if max_val is not None and not math.isinf(max_val) else None

        # Check for actual violations
        if check_min is not None and achieved_val < (check_min - TOLERANCE):
            violations[display_prop] = {
                'type': 'min', 'required': check_min, 'achieved': achieved_val,
                'violation': check_min - achieved_val, 'is_hard': prop in HARD_CONSTRAINTS
            }
        if check_max is not None and achieved_val > (check_max + TOLERANCE):
            violations[display_prop] = {
                'type': 'max', 'required': check_max, 'achieved': achieved_val,
                'violation': achieved_val - check_max, 'is_hard': prop in HARD_CONSTRAINTS
            }
    
    return violations

def write_timestamp_header_to_stringio(file_handle, title):
    """Write a standardized timestamp header to a StringIO object"""
    try:
        now_with_server_tz = datetime.now().astimezone()
    except ValueError:
        now_with_server_tz = datetime.now()

    file_handle.write("=" * 80 + "\n")
    file_handle.write(f"{title}\n")
    file_handle.write("=" * 80 + "\n")
    file_handle.write(f"Generated (Local Server Time): {now_with_server_tz.strftime('%Y-%m-%d %H:%M:%S')}\n")
    file_handle.write(f"Report Date (Local Server Time): {now_with_server_tz.strftime('%A, %B %d, %Y')}\n")
    file_handle.write(f"Generation Time (Local Server Time): {now_with_server_tz.strftime('%I:%M:%S %p %Z%z')}\n")
    file_handle.write("=" * 80 + "\n\n")

def prepare_specs_for_template(specs_data):
    """Prepare specs data for Jinja2 template by converting inf values to large numbers"""
    prepared_specs = {}
    for prop, grades in specs_data.items():
        prepared_specs[prop] = {}
        for grade, bounds in grades.items():
            prepared_specs[prop][grade] = {
                'min': bounds['min'] if not math.isinf(bounds['min']) else 0,
                'max': bounds['max'] if not math.isinf(bounds['max']) else 999999
            }
    return prepared_specs

def make_glpk_safe_name(name):
    """Convert names to GLPK-safe identifiers by replacing spaces with underscores"""
    return name.replace(' ', '_').replace('-', '_')

def get_infeasible_blend_selective(grade_name, grade_idx, grades_data, components_data,
                                  properties_list, specs_data, spec_bounds,
                                  hard_constraints=None, soft_constraint_penalties=None):
    """Get the best possible blend with selective constraint relaxation"""
    if hard_constraints is None:
        hard_constraints = HARD_CONSTRAINTS
    if soft_constraint_penalties is None:
        soft_constraint_penalties = SOFT_CONSTRAINT_PENALTIES

    grade_min, grade_max, grade_price = grades_data[grade_idx]['min'], grades_data[grade_idx]['max'], grades_data[grade_idx]['price']
    components = [c['name'] for c in components_data]
    component_cost = {c['name']: c['cost'] for c in components_data}
    component_availability = {c['name']: c['availability'] for c in components_data}
    component_min_comp = {c['name']: c['min_comp'] for c in components_data}

    property_value = {}
    for comp_data in components_data:
        for prop in properties_list:
            property_value[(prop, comp_data['name'])] = comp_data['properties'].get(prop, 0.0)

    model = LpProblem(f"{grade_name}_Selective_Relaxed", LpMaximize)
    blend = {comp: LpVariable(f"Blend_{grade_name}_{comp}", lowBound=0, cat='Continuous') for comp in components}
    slack_vars, penalty_sum = {}, 0
    total_blend = lpSum([blend[comp] for comp in components])

    # Add slack variables only for soft constraints
    for prop in properties_list:
        if prop in hard_constraints:
            continue
        min_val, max_val = spec_bounds.get((prop, grade_name), (0.0, float('inf')))
        penalty = soft_constraint_penalties.get(prop, 1000)
        
        if min_val is not None and not math.isinf(min_val) and min_val > 0:
            slack_vars[(prop, 'min')] = LpVariable(f"Slack_{grade_name}_{prop}_min", lowBound=0)
            penalty_sum += slack_vars[(prop, 'min')] * penalty
        if max_val is not None and not math.isinf(max_val):
            slack_vars[(prop, 'max')] = LpVariable(f"Slack_{grade_name}_{prop}_max", lowBound=0)
            penalty_sum += slack_vars[(prop, 'max')] * penalty

    # Objective: maximize profit minus penalties
    profit = grade_price * total_blend - lpSum([component_cost[comp] * blend[comp] for comp in components])
    model += profit - penalty_sum, "Profit_minus_penalties"

    # Volume constraints (always hard)
    model += total_blend >= grade_min, f"{grade_name}_Min"
    model += total_blend <= grade_max, f"{grade_name}_Max"

    # Component constraints (always hard)
    for comp in components:
        model += blend[comp] <= component_availability[comp], f"{comp}_Availability"
        min_comp_val = component_min_comp.get(comp, 0)
        if min_comp_val is not None and min_comp_val > 0:
            model += blend[comp] >= min_comp_val, f"{comp}_Min"

    # Property constraints with selective relaxation
    for prop in properties_list:
        min_val, max_val = spec_bounds.get((prop, grade_name), (0.0, float('inf')))
        weighted_sum = lpSum([property_value.get((prop, comp), 0) * blend[comp] for comp in components])

        if prop in hard_constraints:
            # HARD CONSTRAINT - No slack allowed
            if min_val is not None and not math.isinf(min_val) and min_val > 0:
                model += weighted_sum >= min_val * total_blend, f"{grade_name}_{prop}_Min_Hard"
            if max_val is not None and not math.isinf(max_val):
                model += weighted_sum <= max_val * total_blend, f"{grade_name}_{prop}_Max_Hard"
        else:
            # SOFT CONSTRAINT - Can be relaxed with penalties
            if min_val is not None and not math.isinf(min_val) and min_val > 0 and (prop, 'min') in slack_vars:
                model += weighted_sum + slack_vars[(prop, 'min')] >= min_val * total_blend, f"{grade_name}_{prop}_Min_Soft"
            if max_val is not None and not math.isinf(max_val) and (prop, 'max') in slack_vars:
                model += weighted_sum - slack_vars[(prop, 'max')] <= max_val * total_blend, f"{grade_name}_{prop}_Max_Soft"

    model.solve(PULP_CBC_CMD(msg=0))
    return model, blend, total_blend, slack_vars

def get_infeasible_blend(grade_name, grade_idx, grades_data, components_data, properties_list, specs_data, spec_bounds):
    """Get the best possible blend even if infeasible by relaxing ALL constraints"""
    return get_infeasible_blend_selective(
        grade_name, grade_idx, grades_data, components_data, properties_list, specs_data, spec_bounds,
        hard_constraints=[], soft_constraint_penalties={prop: 1000 for prop in properties_list}
    )

def analyze_grade_infeasibility(grade_name, grade_idx, grades_data, components_data, properties_list, specs_data, original_specs_data, spec_bounds):
    """Simplified infeasibility analysis with early exit for successful selective relaxation"""
    diagnostics = [f"ENHANCED INFEASIBILITY ANALYSIS FOR {grade_name}", "=" * 70]
    
    try:
        # Verify infeasibility
        diagnostics.extend(["1. CONFIRMED: Model is infeasible as stated", ""])
        
        # Try selective relaxation first
        diagnostics.append("2. ATTEMPTING SELECTIVE RELAXATION (keeping regulatory constraints)")
        relaxed_model, relaxed_blend, relaxed_total, slack_vars = get_infeasible_blend_selective(
            grade_name, grade_idx, grades_data, components_data, properties_list, specs_data, spec_bounds
        )
        
        components = [c['name'] for c in components_data]
        property_value = {(prop, comp['name']): comp['properties'].get(prop, 0.0) 
                         for comp in components_data for prop in properties_list}
        
        if relaxed_model.status == LpStatusOptimal:
            # SUCCESS - Early exit
            diagnostics.extend([
                "   ✓ Found solution with selective relaxation",
                f"   Hard constraints maintained: {', '.join(HARD_CONSTRAINTS)}",
                "", "FEASIBILITY SUMMARY & RECOMMENDATIONS", "=" * 50,
                "✅ SOLUTION FOUND: Selective relaxation successful",
                "• All regulatory constraints (HARD) are satisfied",  
                "• Some operational constraints (SOFT) may be violated",
                "• This is an acceptable compromise for regulatory compliance"
            ])
            
            blend_data = {comp: relaxed_blend[comp].varValue or 0 for comp in components}
            violations = check_violations(blend_data, components, property_value, spec_bounds, grade_name, properties_list)
            
            infeasible_blend_data = {
                'blend': blend_data,
                'total_volume': sum(blend_data.values()),
                'violations': violations,
                'method': 'selective'
            }
            
            return diagnostics, infeasible_blend_data, property_value
        
        # If selective fails, try full relaxation
        diagnostics.extend([
            "   ✗ Selective relaxation failed (hard constraints too restrictive)",
            "3. ATTEMPTING FULL RELAXATION (all constraints can be violated)"
        ])
        
        relaxed_model, relaxed_blend, relaxed_total, slack_vars = get_infeasible_blend(
            grade_name, grade_idx, grades_data, components_data, properties_list, specs_data, spec_bounds
        )
        
        if relaxed_model.status == LpStatusOptimal:
            diagnostics.append("   ✓ Found solution with full relaxation")
            blend_data = {comp: relaxed_blend[comp].varValue or 0 for comp in components}
            violations = check_violations(blend_data, components, property_value, spec_bounds, grade_name, properties_list)
            
            infeasible_blend_data = {
                'blend': blend_data,
                'total_volume': sum(blend_data.values()),
                'violations': violations,
                'method': 'full'
            }
            
            diagnostics.extend([
                "", "FEASIBILITY SUMMARY & RECOMMENDATIONS", "=" * 50,
                "⚠️ SOLUTION FOUND: Full relaxation required",
                "• Even regulatory constraints had to be violated",
                "• Problem is severely over-constrained",
                "• Consider relaxing multiple constraints simultaneously"
            ])
            
            return diagnostics, infeasible_blend_data, property_value
        
        # Complete failure
        diagnostics.extend([
            "", "FEASIBILITY SUMMARY & RECOMMENDATIONS", "=" * 50,
            "❌ NO SOLUTION FOUND: Even full relaxation failed",
            "• Problem has fundamental conflicts or impossible constraints",
            "• Review all specifications for feasibility"
        ])
        
        return diagnostics, None, property_value
        
    except Exception as e:
        diagnostics.extend([f"Error during infeasibility analysis: {str(e)}", "This may indicate a deeper issue with the model setup."])
        return diagnostics, None, {}

def format_report_table(file_handle, header, rows, footer_rows=None, alignments=None):
    """Format and write a text table to a file-like object"""
    all_rows = [header] + rows + (footer_rows or [])
    if not alignments:
        alignments = ['left'] + ['right'] * (len(header) - 1)

    column_widths = [max(len(str(item)) for item in col) for col in zip(*all_rows)]
    
    def format_row(data, row_alignments):
        formatted_parts = []
        for i, (item, align) in enumerate(zip(data, row_alignments)):
            width = column_widths[i]
            formatted_item = str(item)
            formatted_parts.append(formatted_item.ljust(width) if align == 'left' else formatted_item.rjust(width))
        return "| " + " | ".join(formatted_parts) + " |\n"

    # Write table
    file_handle.write(format_row(header, ['left'] * len(header)))
    separator_parts = [("-" * width) for width in column_widths]
    file_handle.write("|-" + "-|-".join(separator_parts) + "-|\n")
    
    for row in rows:
        file_handle.write(format_row(row, alignments))
    if footer_rows:
        for footer_row in footer_rows:
            file_handle.write(format_row(footer_row, alignments))

def format_spec_value_concise(val):
    if val is None: return "N/A"
    if math.isinf(val): return "inf"
    if math.isnan(val): return "NaN"
    return f"{val:g}"

def calculate_and_format_blend_data(grade_name, blend_data, components_data, property_values, spec_bounds, original_specs_data, grade_price, is_infeasible=False):
    """Calculate blend properties and format them for the report table"""
    components = [c['name'] for c in components_data]
    component_cost = {c['name']: c['cost'] for c in components_data}
    
    total_volume = sum(blend_data[comp] for comp in components)
    total_cost = sum(component_cost[comp] * blend_data[comp] for comp in components)
    total_revenue = grade_price * total_volume
    profit = total_revenue - total_cost

    # Component rows
    table_rows = []
    for comp in components:
        vol = blend_data[comp]
        row = [comp, f"{vol:.2f}", f"{component_cost[comp]:.2f}"]
        for p in DISPLAY_PROPERTIES_LIST:
            val = property_values.get((p, comp), 0)
            row.append(f"{val:.4f}" if isinstance(val, (int, float)) else str(val))
        table_rows.append(row)

    # Footer rows
    quality_row = ["QUALITY", "", ""]
    spec_row = ["SPEC", "", ""]
    
    for p in DISPLAY_PROPERTIES_LIST:
        if p in ['RON', 'MON', 'RVP']:
            # Calculate from internal counterparts and convert back
            internal_prop = p.replace('ON', 'OI').replace('P', 'I')
            weighted_sum = sum(property_values.get((internal_prop, comp), 0) * blend_data[comp] for comp in components)
            avg_val = weighted_sum / total_volume if total_volume > 0 else 0
            
            if p == 'RON':
                calculated_value = reverse_roi_to_ron(avg_val) if avg_val > 0 else 0
            elif p == 'MON':
                calculated_value = reverse_moi_to_mon(avg_val) if avg_val > 0 else 0
            else:  # RVP
                calculated_value = reverse_rvi_to_rvp(avg_val) if avg_val > 0 else 0
        else:
            # Simple weighted average
            weighted_sum = sum(property_values.get((p, comp), 0) * blend_data[comp] for comp in components)
            calculated_value = weighted_sum / total_volume if total_volume > 0 else 0
        
        quality_row.append(f"{calculated_value:.4f}")
        
        # Format spec string
        spec_data = original_specs_data.get(p, {}).get(grade_name, {"min": 0, "max": float('inf')})
        min_spec_val, max_spec_val = spec_data["min"], spec_data["max"]
        formatted_min = format_spec_value_concise(min_spec_val)
        formatted_max = format_spec_value_concise(max_spec_val)
        spec_row.append(f"{formatted_min}-{formatted_max}")
    
    combined_total_row = ["TOTAL", f"{total_volume:.2f}", f"{total_cost:.2f}"] + [""] * len(DISPLAY_PROPERTIES_LIST)
    
    return total_volume, total_cost, total_revenue, profit, table_rows, [combined_total_row, quality_row, spec_row]

# --- Core LP Optimization Logic ---
def run_optimization(grades_data, components_data, properties_list, specs_data, solver_choice):
    """Main optimization function"""
    original_specs_data = specs_data.copy()
    components_data = convert_component_properties(components_data)
    specs_data = convert_specs_to_internal(specs_data)

    grades = [g['name'] for g in grades_data]
    barrel_min = [g['min'] for g in grades_data]
    barrel_max = [g['max'] for g in grades_data]
    gasoline_price = [g['price'] for g in grades_data]
    components = [c['name'] for c in components_data]

    if not components:
        raise ValueError("No components found for optimization.")

    component_cost = {c['name']: c['cost'] for c in components_data}
    component_availability = {c['name']: c['availability'] for c in components_data}
    component_min_comp = {c['name']: c['min_comp'] for c in components_data}

    property_value = {}
    for comp_data in components_data:
        for prop in properties_list:
            property_value[(prop, comp_data['name'])] = comp_data['properties'].get(prop, 0.0)

    spec_bounds = {}
    for prop_name, grade_specs in specs_data.items():
        for grade_name, bounds in grade_specs.items():
            spec_bounds[(prop_name, grade_name)] = (bounds['min'], bounds['max'])

    # Create and solve main model
    model = LpProblem("Gasoline_Blending", LpMaximize)
    blend = LpVariable.dicts("Blend", (grades, components), lowBound=0, cat='Continuous')

    # Objective
    model += lpSum([
        gasoline_price[i] * lpSum([blend[grades[i]][comp] for comp in components]) -
        lpSum([component_cost[comp] * blend[grades[i]][comp] for comp in components])
        for i in range(len(grades))
    ]), "Total_Profit"

    # Volume constraints
    for i in range(len(grades)):
        total = lpSum([blend[grades[i]][comp] for comp in components])
        model += total >= barrel_min[i], f"{grades[i]}_Min"
        model += total <= barrel_max[i], f"{grades[i]}_Max"

    # Property constraints
    for g in grades:
        total_blend = lpSum([blend[g][comp] for comp in components])
        for p in properties_list:
            weighted_sum = lpSum([property_value.get((p, comp), 0) * blend[g][comp] for comp in components])
            min_val, max_val = spec_bounds.get((p, g), (0.0, float('inf')))

            if min_val is not None and not math.isinf(min_val) and not math.isnan(min_val):
                model += weighted_sum >= min_val * total_blend, f"{g}_{p}_Min"
            if max_val is not None and not math.isinf(max_val) and not math.isnan(max_val):
                model += weighted_sum <= max_val * total_blend, f"{g}_{p}_Max"

    # Component constraints
    for comp in components:
        model += lpSum([blend[g][comp] for g in grades]) <= component_availability[comp], f"{comp}_Availability_Max"
        min_comp_val = component_min_comp.get(comp, 0)
        if min_comp_val is not None and min_comp_val > 0:
            model += lpSum([blend[g][comp] for g in grades]) >= min_comp_val, f"{comp}_Min_Comp"

    # Solve with appropriate solver
    solver_used = "CBC"
    try:
        if solver_choice == "GLPK":
            try:
                subprocess.run(['glpsol', '--version'], capture_output=True, text=True, timeout=5, check=True)
                model.solve(GLPK_CMD(msg=0, path=GLPSOL_PATH))
                solver_used = "GLPK"
            except (subprocess.CalledProcessError, FileNotFoundError):
                model.solve(PULP_CBC_CMD(msg=0))
                solver_used = "CBC (GLPK not available)"
        else:
            model.solve(PULP_CBC_CMD(msg=0))
    except Exception as e:
        model.solve(PULP_CBC_CMD(msg=0))
        solver_used = "CBC (Fallback)"

    # Generate reports
    result1_content = io.StringIO()
    write_timestamp_header_to_stringio(result1_content, "GASOLINE BLENDING OPTIMIZATION REPORT")

    overall_status = LpStatus[model.status]
    result1_content.write(f"Overall Status: {overall_status}\n")
    result1_content.write(f"Solver Used: {solver_used}\n")
    if model.status == LpStatusOptimal:
        result1_content.write(f"Objective Value (Profit): {value(model.objective):.2f}\n")
    result1_content.write("\n")

    # Grade Overview
    result1_content.write("=== Gasoline Grade Overview ===\n")
    grade_overview_header = ["GASOLINE", "MIN", "MAX", "PRICE"]
    grade_overview_rows = [[g['name'], f"{g['min']:.0f}", f"{g['max']:.0f}", f"{g['price']:.0f}"] for g in grades_data]
    format_report_table(result1_content, grade_overview_header, grade_overview_rows)
    result1_content.write("\n")

    # Process results for each grade
    grade_results = {}
    infeasibility_report_stringio = io.StringIO()
    write_timestamp_header_to_stringio(infeasibility_report_stringio, "GRADE INFEASIBILITY ANALYSIS REPORT")
    has_infeasible_grades = False

    if model.status != LpStatusOptimal:
        # Try solving each grade individually
        for current_grade_idx, current_grade in enumerate(grades):
            single_model = LpProblem(f"{current_grade}_Only", LpMaximize)
            single_blend = LpVariable.dicts("Blend", components, lowBound=0, cat='Continuous')
            single_model += (gasoline_price[current_grade_idx] * lpSum(single_blend.values()) - 
                           lpSum(component_cost[comp] * single_blend[comp] for comp in components)), "Profit"
            
            total = lpSum(single_blend.values())
            single_model += total >= barrel_min[current_grade_idx], f"{current_grade}_Min"
            single_model += total <= barrel_max[current_grade_idx], f"{current_grade}_Max"

            for p in properties_list:
                weighted_sum = lpSum(property_value.get((p, comp), 0) * single_blend[comp] for comp in components)
                min_val, max_val = spec_bounds.get((p, current_grade), (0.0, float('inf')))
                if min_val is not None and not math.isinf(min_val) and not math.isnan(min_val):
                    single_model += weighted_sum >= min_val * total, f"{current_grade}_{p}_Min"
                if max_val is not None and not math.isinf(max_val) and not math.isnan(max_val):
                    single_model += weighted_sum <= max_val * total, f"{current_grade}_{p}_Max"
            
            for comp in components:
                single_model += single_blend[comp] <= component_availability[comp], f"{comp}_Availability"
                min_comp_val = component_min_comp.get(comp, 0)
                if min_comp_val is not None and min_comp_val > 0:
                    single_model += single_blend[comp] >= min_comp_val, f"{comp}_Min"

            single_model.solve(PULP_CBC_CMD(msg=0))
            
            grade_results[current_grade] = {
                'status': LpStatus[single_model.status],
                'model': single_model,
                'blend': single_blend,
                'profit': value(single_model.objective) if single_model.status == LpStatusOptimal else 0
            }
    else:
        # All grades optimal
        for current_grade in grades:
            grade_results[current_grade] = {
                'status': 'Optimal', 'model': model, 'blend': blend[current_grade], 'profit': 0
            }

    # Display results for each grade
    for current_grade_idx, current_grade in enumerate(grades):
        grade_selling_price = gasoline_price[current_grade_idx]
        result1_content.write(f"\n{'='*60}\n{current_grade} GASOLINE\n{'='*60}\n")
        result1_content.write(f"Status: {grade_results[current_grade]['status']}\n")
        result1_content.write(f"Price: ${grade_selling_price:.2f}/bbl\n")

        if grade_results[current_grade]['status'] != 'Optimal':
            result1_content.write("\n⚠️ INFEASIBILITY DETECTED - Showing Best Possible (Constraint-Violating) Blend\n")

            diagnostics, infeasible_blend_data, prop_values = analyze_grade_infeasibility(
                current_grade, current_grade_idx, grades_data, components_data,
                properties_list, specs_data, original_specs_data, spec_bounds
            )
            has_infeasible_grades = True
            for diag in diagnostics:
                infeasibility_report_stringio.write(diag + "\n")
            infeasibility_report_stringio.write("\n" + "="*80 + "\n\n")

            if infeasible_blend_data and infeasible_blend_data['total_volume'] > 0:
                result1_content.write("\n=== INFEASIBLE BLEND COMPOSITION ===\n")
                method_desc = "Selective relaxation - regulatory constraints maintained" if infeasible_blend_data.get('method') == 'selective' else "Full relaxation - best achievable blend"
                result1_content.write(f"({method_desc})\n\n")

                if infeasible_blend_data['violations']:
                    result1_content.write("CONSTRAINT VIOLATIONS:\n")
                    for prop_name, violation_info in infeasible_blend_data['violations'].items():
                        constraint_type = "[HARD]" if violation_info.get('is_hard', False) else "[SOFT]"
                        if violation_info['type'] == 'min':
                            result1_content.write(f"  ❌ {prop_name} {constraint_type}: {violation_info['achieved']:.3f} < {violation_info['required']:.3f} (deficit: {violation_info['violation']:.3f})\n")
                        else:
                            result1_content.write(f"  ❌ {prop_name} {constraint_type}: {violation_info['achieved']:.3f} > {violation_info['required']:.3f} (excess: {violation_info['violation']:.3f})\n")
                    result1_content.write("\n")

                total_vol, total_cost, total_revenue, profit, table_rows, footer_rows = calculate_and_format_blend_data(
                    current_grade, infeasible_blend_data['blend'], components_data, prop_values, 
                    spec_bounds, original_specs_data, grade_selling_price, is_infeasible=True
                )
                
                result1_content.write(f"Total Volume: {total_vol:.2f} bbl\n")
                result1_content.write(f"Total Cost: ${total_cost:.2f}\n")
                result1_content.write(f"Total Revenue: ${total_revenue:.2f}\n")
                result1_content.write(f"Profit (if constraints ignored): ${profit:.2f}\n\n")

                header_row = ["Component Name", "Vol(bbl)", "Cost($)"] + DISPLAY_PROPERTIES_LIST
                format_report_table(result1_content, header_row, table_rows, footer_rows)
                result1_content.write("\nSee infeasibility_analysis.txt for detailed constraint analysis\n")
            else:
                result1_content.write("\nUnable to generate even an infeasible blend. Problem is severely constrained.\n")
                result1_content.write("See infeasibility_analysis.txt for detailed analysis\n\n")
            continue

        # For feasible grades, show optimal blend
        result1_content.write(f"\n=== Calculated Properties of '{current_grade}' Optimized Blend ===\n")
        
        current_blend_values = {comp: grade_results[current_grade]['blend'][comp].varValue or 0 for comp in components}
        
        total_vol, total_cost, total_revenue, profit, table_rows, footer_rows = calculate_and_format_blend_data(
            current_grade, current_blend_values, components_data, property_value, 
            spec_bounds, original_specs_data, grade_selling_price
        )

        result1_content.write(f"Total Volume: {total_vol:.2f} bbl\n")
        result1_content.write(f"Total Cost: ${total_cost:.2f}\n")
        result1_content.write(f"Total Revenue: ${total_revenue:.2f}\n")
        result1_content.write(f"Profit: ${profit:.2f}\n\n")

        header_row = ["Component Name", "Vol(bbl)", "Cost($)"] + DISPLAY_PROPERTIES_LIST
        format_report_table(result1_content, header_row, table_rows, footer_rows)

    # Component Summary
    result1_content.write("\n\n=== Component Summary ===\n")
    component_summary_header = ["Component", "Available (bbl)", "Used (bbl)"]
    component_summary_rows = []
    
    for comp in components:
        if model.status == LpStatusOptimal:
            total_used_volume = sum(blend[g][comp].varValue or 0 for g in grades)
        else:
            total_used_volume = sum(
                (grade_results[g]['blend'][comp].varValue or 0)
                for g in grades if grade_results[g]['status'] == 'Optimal'
            )
        available_quantity = component_availability.get(comp, 0)
        component_summary_rows.append([comp, f"{available_quantity:.2f}", f"{total_used_volume:.2f}"])
        
    format_report_table(result1_content, component_summary_header, component_summary_rows)
    result1_content.seek(0)
    
    # Replace the simplified range analysis section in run_optimization function with this:

    # Generate sensitivity analysis report
    range_report_content = io.StringIO()
    if solver_choice == "GLPK" and model.status == LpStatusOptimal:
        try:
            mod_file_path = MOD_FILE
            dat_file_path = DAT_FILE

            # --- MathProg File Generation ---
            env = Environment(
                loader=FileSystemLoader(BASE_PATH),
                undefined=StrictUndefined
            )

            mod_template_str = """
set GRADES;
set COMPONENTS;
set PROPERTIES;

param price{GRADES};
param min_volume{GRADES};
param max_volume{GRADES};

param cost{COMPONENTS};
param max_availability{COMPONENTS};
param min_comp_requirement{COMPONENTS};

param prop_value{COMPONENTS, PROPERTIES};
param spec_min{PROPERTIES, GRADES};
param spec_max{PROPERTIES, GRADES};

var blend{g in GRADES, c in COMPONENTS} >= 0;

maximize Total_Profit:
    sum{g in GRADES} (
        price[g] * sum{c in COMPONENTS} blend[g, c] -
        sum{c in COMPONENTS} cost[c] * blend[g, c]
    );

s.t. Min_Volume{g in GRADES}:
    sum{c in COMPONENTS} blend[g, c] >= min_volume[g];

s.t. Max_Volume{g in GRADES}:
    sum{c in COMPONENTS} blend[g, c] <= max_volume[g];

s.t. Component_Availability{c in COMPONENTS}:
    sum{g in GRADES} blend[g, c] <= max_availability[c];

s.t. Component_Min_Requirement{c in COMPONENTS}:
    sum{g in GRADES} blend[g, c] >= min_comp_requirement[c];

s.t. Property_Min{p in PROPERTIES, g in GRADES}:
    sum{c in COMPONENTS} prop_value[c, p] * blend[g, c] >= spec_min[p, g] * sum{c in COMPONENTS} blend[g, c];

s.t. Property_Max{p in PROPERTIES, g in GRADES}:
    sum{c in COMPONENTS} prop_value[c, p] * blend[g, c] <= spec_max[p, g] * sum{c in COMPONENTS} blend[g, c];

solve;

end;
"""

            dat_template_str = """
set GRADES := {% for g in grades %}{{ make_glpk_safe_name(g.name) }} {% endfor %};
set COMPONENTS := {% for c in components %}{{ make_glpk_safe_name(c.name) }} {% endfor %};
set PROPERTIES := {% for p in properties %}{{ p }} {% endfor %};

param price := {% for g in grades %}{{ make_glpk_safe_name(g.name) }} {{ g.price }} {% endfor %};
param min_volume := {% for g in grades %}{{ make_glpk_safe_name(g.name) }} {{ g.min }} {% endfor %};
param max_volume := {% for g in grades %}{{ make_glpk_safe_name(g.name) }} {{ g.max }} {% endfor %};

param cost := {% for c in components %}{{ make_glpk_safe_name(c.name) }} {{ c.cost }} {% endfor %};
param max_availability := {% for c in components %}{{ make_glpk_safe_name(c.name) }} {{ c.availability }} {% endfor %};
param min_comp_requirement := {% for c in components %}{{ make_glpk_safe_name(c.name) }} {{ c.min_comp }} {% endfor %};

param prop_value: {% for p in properties %}{{ p }} {% endfor %} :=
{% for c in components %} {{ make_glpk_safe_name(c.name) }} {% for p in properties %}{{ c.properties.get(p, 0) }} {% endfor %}{% endfor %};

param spec_min: {% for g in grades %}{{ make_glpk_safe_name(g.name) }} {% endfor %} :=
{% for p in properties %} {{ p }} {% for g in grades %}{{ prepared_specs.get(p, {}).get(g.name, {}).get('min', 0) }} {% endfor %}{% endfor %};

param spec_max: {% for g in grades %}{{ make_glpk_safe_name(g.name) }} {% endfor %} :=
{% for p in properties %} {{ p }} {% for g in grades %}{{ prepared_specs.get(p, {}).get(g.name, {}).get('max', 999999) }} {% endfor %}{% endfor %};

end;
"""

            prepared_specs = prepare_specs_for_template(specs_data)
            from jinja2 import Template
            mod_template = Template(mod_template_str)
            dat_template = Template(dat_template_str)

            grades_raw = grades_data
            components_raw = components_data
            properties_raw = properties_list

            mod_output = mod_template.render()
            dat_output = dat_template.render(
                grades=grades_raw,
                components=components_raw,
                properties=properties_raw,
                prepared_specs=prepared_specs,
                make_glpk_safe_name=make_glpk_safe_name
            )

            with open(mod_file_path, "w") as f:
                f.write(mod_output)
            with open(dat_file_path, "w") as f:
                f.write(dat_output)

            # --- Run GLPK Range Analysis ---
            range_output_file = os.path.join(BASE_PATH, "temp_range_output.txt")
            glpsol_range_command = ["glpsol", "--math", mod_file_path, "--data", dat_file_path, "--ranges", range_output_file]

            result = subprocess.run(glpsol_range_command, capture_output=True, text=True, timeout=60)

            # Add these lines to delete the .mod and .dat files
            if os.path.exists(mod_file_path):
                os.remove(mod_file_path)
            if os.path.exists(dat_file_path):
               os.remove(dat_file_path)
                                  
            
            if result.returncode == 0 and os.path.exists(range_output_file):
                write_timestamp_header_to_stringio(range_report_content, "GLPK RANGE ANALYSIS REPORT")
                with open(range_output_file, 'r', encoding='utf-8') as temp_f:
                    range_report_content.write(temp_f.read())
                os.remove(range_output_file) # Clean up temp file
            else:
                range_report_content = io.StringIO()
                write_timestamp_header_to_stringio(range_report_content, "GLPK RANGE ANALYSIS REPORT")
                range_report_content.write("GLPK Range Analysis is only available for GLPK solver with an Optimal solution.\n")
                if os.path.exists(range_output_file):
                    os.remove(range_output_file) # Clean up failed temp file

        except Exception as e:
            range_report_content = io.StringIO()
            write_timestamp_header_to_stringio(range_report_content, "GLPK RANGE ANALYSIS REPORT")
            range_report_content.write(f"Error during GLPK Range Analysis: {str(e)}\n")
            range_report_content.write("Range analysis is only available for GLPK solver with an Optimal solution.\n")

    else:
        range_report_content = io.StringIO()
        write_timestamp_header_to_stringio(range_report_content, "GLPK RANGE ANALYSIS REPORT")
        range_report_content.write("GLPK Range Analysis is only available for GLPK solver with an Optimal solution.\n")

    range_report_content.seek(0)

    # Finalize infeasibility report
    if not has_infeasible_grades:
        infeasibility_report_stringio.write("All grades were successfully optimized. No infeasibility issues found.\n")
    infeasibility_report_stringio.seek(0)

    return result1_content.getvalue(), range_report_content.getvalue(), infeasibility_report_stringio.getvalue()

# --- Flask Routes ---
load_dotenv()
APP_USERNAME = os.environ.get("APP_USERNAME")
APP_PASSWORD = os.environ.get("APP_PASSWORD")

@app.route('/')
def login_page():
    message = request.args.get('message', '')
    return render_template('login.html', message=message)

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')
    if username == APP_USERNAME and password == APP_PASSWORD:
        return redirect('/index')
    else:
        return redirect(url_for('login_page', message='Invalid username or password'))

@app.route('/get_brent_price')
def get_brent_price():
    try:
        data = yf.Ticker("BZ=F")
        price = data.history(period="1d")['Close'].iloc[-1]
        return jsonify({'price': round(price, 2)})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/get_brent_chart_data')
def get_brent_chart_data():
    try:
        data = yf.Ticker("BZ=F")
        history = data.history(period="1mo")['Close']
        labels = [d.strftime('%Y-%m-%d') for d in history.index]
        values = history.tolist()
        return jsonify({'labels': labels, 'values': values})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/index')
def index():
    grades_initial = [
        {"name": "Regular", "min": 4000.000000, "max": 400000.000000, "price": 100.000000},
        {"name": "Premium", "min": 0.000000, "max": 400000.000000, "price": 110.000000},
        {"name": "Super Premium", "min": 0.000000, "max": 4000.000000, "price": 200.000000}
    ]
    
    components_initial = [
        {"name": "C4B", "tag": "Alkyl Butane", "min_comp": 0.0, "availability": 1000000.000000, "factor": 1.300000, "cost": 130.000000,
         "properties": {"SPG": 0.584400, "SUL": 0.000100, "RON": 93.800000, "MON": 89.600000, "RVP": 3.191000, "E70": 100.000000, "E10": 100.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 0.000000, "OXY": 0.000000, "OLEFIN": 0.000000, "ETH": 0}},
        {"name": "IS1", "tag": "Isomerate", "min_comp": 0.00, "availability": 1000000.000000, "factor": 1.250000, "cost": 125.000000,
         "properties": {"SPG": 0.661000, "SUL": 0.500000, "RON": 88.560000, "MON": 86.150000, "RVP": 0.839000, "E70": 92.000000, "E10": 100.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 0.000000, "OXY": 0.000000, "OLEFIN": 0.000000, "ETH": 0}},
        {"name": "RFL", "tag": "Reformate", "min_comp": 0.00, "availability": 1000000.000000, "factor": 1.050000, "cost": 105.000000,
         "properties": {"SPG": 0.819000, "SUL": 0.000000, "RON": 97.000000, "MON": 86.150000, "RVP": 0.139000, "E70": 0.001000, "E10": 4.000000, "E15": 67.300000, "ARO": 61.800000, "BEN": 0.438400, "OXY": 0.000000, "OLEFIN": 0.775600, "ETH": 0}},
        {"name": "F5X", "tag": "Mixed RFC", "min_comp": 0.00, "availability": 1000000.000000, "factor": 0.700000, "cost": 70.000000,
         "properties": {"SPG": 0.644700, "SUL": 10.000000, "RON": 94.600000, "MON": 89.650000, "RVP": 1.310000, "E70": 100.000000, "E10": 100.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 1.160000, "OXY": 0.000000, "OLEFIN": 57.700000, "ETH": 0}},
        {"name": "RCG", "tag": "FCC Gasoline", "min_comp": 0, "availability": 1000000.000000, "factor": 0.900000, "cost": 90.000000,
         "properties": {"SPG": 0.785600, "SUL": 20.000000, "RON": 94.430000, "MON": 82.440000, "RVP": 0.210000, "E70": 8.854800, "E10": 36.400000, "E15": 67.300000, "ARO": 50.400000, "BEN": 1.718300, "OXY": 0.000000, "OLEFIN": 19.670000, "ETH": 0}},
        {"name": "IC4", "tag": "DIB IC4", "min_comp": 0, "availability": 1000000.000000, "factor": 0.900000, "cost": 90.000000,
         "properties": {"SPG": 0.563300, "SUL": 10.000000, "RON": 100.050000, "MON": 97.540000, "RVP": 4.347000, "E70": 100.000000, "E10": 100.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 0.000000, "OXY": 0.000000, "OLEFIN": 0.000000, "ETH": 0}},
        {"name": "HBY", "tag": "SHIP C4", "min_comp": 0, "availability": 1000000.000000, "factor": 0.750000, "cost": 75.000000,
         "properties": {"SPG": 0.593600, "SUL": 10.000000, "RON": 98.200000, "MON": 89.000000, "RVP": 3.674000, "E70": 100.000000, "E10": 100.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 0.000000, "OXY": 0.000000, "OLEFIN": 60.800000, "ETH": 0}},
        {"name": "AKK", "tag": "Alkylate", "min_comp": 0.0, "availability": 1000000.000000, "factor": 0.700000, "cost": 70.000000,
         "properties": {"SPG": 0.703200, "SUL": 0.000100, "RON": 76.130000, "MON": 92.000000, "RVP": 0.403000, "E70": 10.000000, "E10": 35.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 0.000000, "OXY": 0.000000, "OLEFIN": 0.000000, "ETH": 0}},
        {"name": "ETH", "tag": "Ethanol", "min_comp": 0.0, "availability": 1000000.000000, "factor": 0.750000, "cost": 75.000000,
         "properties": {"SPG": 0.791000, "SUL": 1.000000, "RON": 128.000000, "MON": 100.000000, "RVP": 1.329000, "E70": 50.000000, "E10": 100.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 0.000000, "OXY": 34.780000, "OLEFIN": 0.000000, "ETH": 100}},
        {"name": "LTN", "tag": "Light Naptha", "min_comp": 0.0, "availability": 1000000.000000, "factor": 0.750000, "cost": 75.000000,
         "properties": {"SPG": 0.791000, "SUL": 1.000000, "RON": 128.000000, "MON": 100.000000, "RVP": 1.329000, "E70": 50.000000, "E10": 100.000000, "E15": 100.000000, "ARO": 0.000000, "BEN": 0.000000, "OXY": 34.780000, "OLEFIN": 0.000000, "ETH": 0}},
    ]
    
    regular_gasoline_price = next((g['price'] for g in grades_initial if g['name'] == 'Regular'), 100.00)
    for comp in components_initial:
        comp['display_cost'] = comp['factor'] * regular_gasoline_price
        comp['cost'] = comp['display_cost']
    
    specs_initial = {
        "SPG": {"Regular": {"min": 0.720000, "max": 0.780000}, "Premium": {"min": 0.720000, "max": 0.780000}, "Super Premium": {"min": 0.720000, "max": 0.780000}},
        "SUL": {"Regular": {"min": 0.000000, "max": 10.000000}, "Premium": {"min": 0.000000, "max": 10.000000}, "Super Premium": {"min": 0.000000, "max": 10.000000}},
        "RON": {"Regular": {"min": 91.000000, "max": float('inf')}, "Premium": {"min": 95.000000, "max": float('inf')}, "Super Premium": {"min": 98.000000, "max": float('inf')}},
        "MON": {"Regular": {"min": 82.000000, "max": float('inf')}, "Premium": {"min": 86.000000, "max": float('inf')}, "Super Premium": {"min": 89.000000, "max": float('inf')}},
        "RVP": {"Regular": {"min": 0.000000, "max": 0.700000}, "Premium": {"min": 0.000000, "max": 0.700000}, "Super Premium": {"min": 0.000000, "max": 0.700000}},
        "E70": {"Regular": {"min": 22.000000, "max": 48.000000}, "Premium": {"min": 22.000000, "max": 48.000000}, "Super Premium": {"min": 22.000000, "max": 48.000000}},
        "E10": {"Regular": {"min": 44.000000, "max": 70.000000}, "Premium": {"min": 44.000000, "max": 70.000000}, "Super Premium": {"min": 44.000000, "max": 70.000000}},
        "E15": {"Regular": {"min": 76.000000, "max": float('inf')}, "Premium": {"min": 76.000000, "max": float('inf')}, "Super Premium": {"min": 76.000000, "max": float('inf')}},
        "ARO": {"Regular": {"min": 0.000000, "max": 35.000000}, "Premium": {"min": 0.000000, "max": 35.000000}, "Super Premium": {"min": 0.000000, "max": 35.000000}},
        "BEN": {"Regular": {"min": 0.000000, "max": 1.000000}, "Premium": {"min": 0.000000, "max": 1.000000}, "Super Premium": {"min": 0.000000, "max": 1.000000}},
        "OXY": {"Regular": {"min": 0.000000, "max": 2.700000}, "Premium": {"min": 0.000000, "max": 2.700000}, "Super Premium": {"min": 0.000000, "max": 2.700000}},
        "OLEFIN": {"Regular": {"min": 0.000000, "max": 15.000000}, "Premium": {"min": 0.000000, "max": 15.000000}, "Super Premium": {"min": 0.000000, "max": 15.000000}},
        "ETH": {"Regular": {"min": 0.000000, "max": 10.000000}, "Premium": {"min": 0.000000, "max": 10.000000}, "Super Premium": {"min": 0.000000, "max": 10.000000}},
    }

    try:
        current_datetime_display = datetime.now().astimezone()
    except ValueError:
        current_datetime_display = datetime.now()

    return render_template('input.html',
                            grades=grades_initial,
                            components=components_initial,
                            properties=ALL_PROPERTIES,
                            specs=specs_initial,
                            current_datetime=current_datetime_display)

@app.route('/run_lp', methods=['POST'])
def run_lp():
    try:
   
        # Parse grades data
        grades_data = []
        for grade_name in GRADE_NAMES:
            try:
                min_val = float(request.form.get(f'grade_{grade_name}_min', '0').strip() or '0')
                max_val = float(request.form.get(f'grade_{grade_name}_max', '0').strip() or '0')
                price_val = float(request.form.get(f'grade_{grade_name}_price', '0').strip() or '0')
                grades_data.append({"name": grade_name, "min": min_val, "max": max_val, "price": price_val})
                               
            except ValueError as e:
                return f"Invalid input for {grade_name} grade: {e}", 400

        # Parse components data
        regular_gasoline_price = next((g['price'] for g in grades_data if g['name'] == 'Regular'), 100.00)
        components_data = []
        for comp_html_key in COMPONENT_HTML_KEYS:
            try:
                comp_tag = COMPONENT_DISPLAY_NAMES.get(comp_html_key, comp_html_key)
                factor = float(request.form.get(f'component_{comp_html_key}_factor', '1.0').strip() or '1.0')
                calculated_cost = factor * regular_gasoline_price
                availability = float(request.form.get(f'component_{comp_html_key}_availability', '0').strip() or '0')
                min_comp = float(request.form.get(f'component_{comp_html_key}_min_comp', '0').strip() or '0')

                comp_properties = {}
                for prop in ALL_PROPERTIES:
                    prop_val_str = request.form.get(f'component_{comp_html_key}_property_{prop}', '0.0').strip()
                    comp_properties[prop] = float(prop_val_str or '0')
                    
                components_data.append({
                    "name": comp_html_key, "tag": comp_tag, "cost": calculated_cost,
                    "availability": availability, "min_comp": min_comp, "factor": factor,
                    "properties": comp_properties
                })
                
            except ValueError as e:
                return f"Invalid input for component {comp_tag}: {e}", 400

        # Parse specs data
        specs_data = {}
        for prop in ALL_PROPERTIES:
            specs_data[prop] = {}
            for grade in grades_data:
                try:
                    min_spec_str = request.form.get(f'spec_{prop}_{grade["name"]}_min', '0').strip()
                    max_spec_str = request.form.get(f'spec_{prop}_{grade["name"]}_max', 'inf').strip()
                    min_spec_val = float(min_spec_str) if min_spec_str and min_spec_str.lower() != 'inf' else 0.0
                    max_spec_val = float(max_spec_str) if max_spec_str and max_spec_str.lower() != 'inf' else float('inf')
                    specs_data[prop][grade['name']] = {"min": min_spec_val, "max": max_spec_val}
                except ValueError as e:
                    return f"Invalid input for spec {prop} for {grade['name']}: {e}", 400

        solver_choice = request.form.get('solver_choice', 'CBC')
      
        result1_content, result2_content, infeasibility_content = run_optimization(
            grades_data, components_data, INTERNAL_PROPERTIES_LIST, specs_data, solver_choice
        )

        # Write results to files
     
        with open(RESULT_FILE_NAME, "w", encoding="utf-8") as f1:
            f1.write(result1_content)
        with open(RANGE_REPORT_FILE_NAME, "w", encoding="utf-8") as f2:
            f2.write(result2_content)
        with open(INFEASIBILITY_FILE_NAME, "w", encoding="utf-8") as f3:
            f3.write(infeasibility_content)
      

        return render_template('results.html',
                                result1_filename=os.path.basename(RESULT_FILE_NAME),
                                result2_filename=os.path.basename(RANGE_REPORT_FILE_NAME),
                                infeasibility_filename=os.path.basename(INFEASIBILITY_FILE_NAME))

    except Exception as e:
        print(f"🔥 CRITICAL ERROR in run_lp: {e}")
        traceback.print_exc()
        return f"INTERNAL ERROR: {str(e)}", 500

@app.route('/download/<filename>')
def download_file(filename):
    try:
        allowed_files = [
            os.path.basename(RESULT_FILE_NAME),
            os.path.basename(RANGE_REPORT_FILE_NAME),
            os.path.basename(INFEASIBILITY_FILE_NAME)
        ]

        if os.path.basename(filename) in allowed_files:
            full_path = os.path.join(BASE_PATH, os.path.basename(filename))
            if os.path.exists(full_path):
                return send_file(full_path, as_attachment=True)
            else:
                return "File not found.", 404
        else:
            return "Unauthorized file access.", 403

    except Exception as e:
        return f"Download error: {str(e)}", 500

@app.route('/health')
def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}, 200

# Main application entry point
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)








            
    

