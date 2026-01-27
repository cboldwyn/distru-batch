"""
Batch ID Finder v1.0.0
Find missing Batch IDs by cross-referencing Distru Packages and Assemblies exports

This tool identifies packages missing Batch IDs and retrieves them by:
1. Finding the package label in the Assemblies export (Output row)
2. Locating the corresponding Input row via Assembly Number
3. Extracting the Batch Number from the Input row

CHANGELOG:
v1.0.0 (2025-01-26)
- Initial release
- Packages and Assemblies CSV upload support
- Automatic batch ID matching via assembly lookup
- Export results to CSV
"""

import streamlit as st
import pandas as pd
import io

# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "1.0.0"

st.set_page_config(
    page_title=f"Batch ID Finder v{VERSION}",
    page_icon="🔍",
    layout="wide"
)

# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================

def load_packages_csv(uploaded_file):
    """
    Load Distru Packages export CSV
    
    Args:
        uploaded_file: Streamlit uploaded file object
        
    Returns:
        tuple: (DataFrame, name) or (None, None) if error
    """
    try:
        df = pd.read_csv(uploaded_file, low_memory=False)
        return df, "Packages"
    except Exception as e:
        st.error(f"Error loading Packages CSV: {str(e)}")
        return None, None


def load_assemblies_csv(uploaded_file):
    """
    Load Distru Assemblies export CSV
    Note: Assemblies exports have 3 header rows that need to be skipped
    
    Args:
        uploaded_file: Streamlit uploaded file object
        
    Returns:
        tuple: (DataFrame, name) or (None, None) if error
    """
    try:
        # Skip the first 3 rows (Date, Filters, blank line)
        df = pd.read_csv(uploaded_file, skiprows=3, low_memory=False)
        return df, "Assemblies"
    except Exception as e:
        st.error(f"Error loading Assemblies CSV: {str(e)}")
        return None, None


# ============================================================================
# DATA PROCESSING FUNCTIONS
# ============================================================================

def find_packages_missing_batch(packages_df):
    """
    Find packages that are missing Distru Batch Number
    
    Args:
        packages_df: Packages DataFrame
        
    Returns:
        DataFrame: Packages with missing batch numbers
    """
    if packages_df is None or packages_df.empty:
        return None
    
    if 'Distru Batch Number' not in packages_df.columns:
        st.error("❌ 'Distru Batch Number' column not found in Packages CSV")
        return None
    
    # Find rows where Distru Batch Number is blank/NaN
    missing_batch = packages_df[packages_df['Distru Batch Number'].isna()].copy()
    
    return missing_batch


def build_assembly_lookup(assemblies_df):
    """
    Build lookup dictionaries for assembly matching
    
    Creates two lookups:
    1. Output Package Number -> Assembly Number
    2. Assembly Number -> Input Batch Number
    
    Args:
        assemblies_df: Assemblies DataFrame
        
    Returns:
        tuple: (output_lookup, input_batch_lookup)
    """
    if assemblies_df is None or assemblies_df.empty:
        return {}, {}
    
    required_cols = ['Assembly Number', 'Input/Output', 'Package Number', 'Batch Number']
    missing_cols = [col for col in required_cols if col not in assemblies_df.columns]
    if missing_cols:
        st.error(f"❌ Missing columns in Assemblies CSV: {', '.join(missing_cols)}")
        return {}, {}
    
    # Lookup 1: Output Package Number -> Assembly Number
    output_rows = assemblies_df[assemblies_df['Input/Output'] == 'Output']
    output_lookup = {}
    for _, row in output_rows.iterrows():
        pkg_num = row['Package Number']
        asm_num = row['Assembly Number']
        if pd.notna(pkg_num) and pd.notna(asm_num):
            output_lookup[pkg_num] = asm_num
    
    # Lookup 2: Assembly Number -> Input Batch Number
    input_rows = assemblies_df[assemblies_df['Input/Output'] == 'Input']
    input_batch_lookup = {}
    for _, row in input_rows.iterrows():
        asm_num = row['Assembly Number']
        batch_num = row['Batch Number']
        if pd.notna(asm_num) and pd.notna(batch_num):
            # If multiple inputs, keep the first one with a batch number
            if asm_num not in input_batch_lookup:
                input_batch_lookup[asm_num] = batch_num
    
    return output_lookup, input_batch_lookup


def find_batch_ids(missing_batch_df, output_lookup, input_batch_lookup):
    """
    Find Batch IDs for packages missing them
    
    Logic:
    1. Take Package Label from missing package
    2. Find it in output_lookup to get Assembly Number
    3. Use Assembly Number in input_batch_lookup to get Batch ID
    
    Args:
        missing_batch_df: Packages missing batch IDs
        output_lookup: Package Number -> Assembly Number mapping
        input_batch_lookup: Assembly Number -> Batch Number mapping
        
    Returns:
        DataFrame: Results with found Batch IDs
    """
    if missing_batch_df is None or missing_batch_df.empty:
        return None
    
    results = []
    
    for idx, row in missing_batch_df.iterrows():
        package_label = row.get('Package Label')
        distru_id = row.get('ID')
        distru_product = row.get('Distru Product')
        
        # Initialize result
        result = {
            'Distru Product': distru_product,
            'Package Label': package_label,
            'ID': distru_id,
            'Batch ID': None,
            'Helper ID': None,
            'Status': 'Not Found'
        }
        
        if pd.isna(package_label):
            result['Status'] = 'Missing Package Label'
            results.append(result)
            continue
        
        # Step 1: Find Assembly Number from output lookup
        assembly_num = output_lookup.get(package_label)
        
        if assembly_num is None:
            result['Status'] = 'Package not found in Assemblies'
            results.append(result)
            continue
        
        result['Helper ID'] = assembly_num
        
        # Step 2: Find Batch Number from input lookup
        batch_id = input_batch_lookup.get(assembly_num)
        
        if batch_id is None:
            result['Status'] = 'No Input Batch found for Assembly'
            results.append(result)
            continue
        
        result['Batch ID'] = batch_id
        result['Status'] = 'Found'
        results.append(result)
    
    return pd.DataFrame(results)


# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    st.title(f"🔍 Batch ID Finder v{VERSION}")
    st.markdown("Find missing Batch IDs by cross-referencing Distru Packages and Assemblies exports")
    
    # ========================================================================
    # SIDEBAR
    # ========================================================================
    
    st.sidebar.header("📊 Data Sources")
    
    st.sidebar.subheader("📦 Packages CSV")
    packages_file = st.sidebar.file_uploader(
        "Upload Distru Packages Export:",
        type=['csv'],
        key="packages",
        help="Export from Distru: Packages report"
    )
    
    st.sidebar.subheader("🔧 Assemblies CSV")
    assemblies_file = st.sidebar.file_uploader(
        "Upload Distru Assemblies Export:",
        type=['csv'],
        key="assemblies",
        help="Export from Distru: Assemblies report"
    )
    
    # Process button
    ready_to_process = packages_file is not None and assemblies_file is not None
    
    if st.sidebar.button("🚀 Find Batch IDs", type="primary", disabled=not ready_to_process):
        with st.spinner("Processing data..."):
            
            # Load Packages
            st.info("📦 Loading Packages CSV...")
            packages_df, _ = load_packages_csv(packages_file)
            
            if packages_df is not None:
                st.session_state['packages_df'] = packages_df
                st.success(f"✅ Loaded {len(packages_df):,} packages")
            else:
                st.error("❌ Failed to load Packages CSV")
                return
            
            # Load Assemblies
            st.info("🔧 Loading Assemblies CSV...")
            assemblies_df, _ = load_assemblies_csv(assemblies_file)
            
            if assemblies_df is not None:
                st.session_state['assemblies_df'] = assemblies_df
                st.success(f"✅ Loaded {len(assemblies_df):,} assembly records")
            else:
                st.error("❌ Failed to load Assemblies CSV")
                return
            
            # Find missing batch packages
            st.info("🔎 Finding packages missing Batch IDs...")
            missing_batch_df = find_packages_missing_batch(packages_df)
            
            if missing_batch_df is None or len(missing_batch_df) == 0:
                st.success("🎉 No packages are missing Batch IDs!")
                st.session_state['results_df'] = None
                return
            
            st.info(f"📋 Found {len(missing_batch_df):,} packages missing Batch IDs")
            st.session_state['missing_batch_df'] = missing_batch_df
            
            # Build assembly lookups
            st.info("🔗 Building assembly lookups...")
            output_lookup, input_batch_lookup = build_assembly_lookup(assemblies_df)
            st.info(f"📊 Indexed {len(output_lookup):,} output packages and {len(input_batch_lookup):,} input batches")
            
            # Find batch IDs
            st.info("🎯 Matching packages to Batch IDs...")
            results_df = find_batch_ids(missing_batch_df, output_lookup, input_batch_lookup)
            
            if results_df is not None:
                st.session_state['results_df'] = results_df
                
                found_count = len(results_df[results_df['Status'] == 'Found'])
                not_found_count = len(results_df[results_df['Status'] != 'Found'])
                
                st.success(f"🎉 Processing complete! Found {found_count:,} Batch IDs, {not_found_count:,} not found")
    
    # Changelog
    with st.sidebar.expander("📋 Version History & Changelog"):
        st.markdown("""
        **v1.0.0** (Current - 2025-01-26)
        - 🆕 Initial release
        - 📦 Packages and Assemblies CSV support
        - 🔗 Automatic batch ID matching
        - 📥 Export results to CSV
        """)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Version {VERSION}**")
    
    # ========================================================================
    # MAIN CONTENT
    # ========================================================================
    
    if 'results_df' in st.session_state and st.session_state['results_df'] is not None:
        results_df = st.session_state['results_df']
        
        # Create tabs
        tab_names = ["📊 Results", "📦 Packages", "🔧 Assemblies"]
        tabs = st.tabs(tab_names)
        
        # Results Tab
        with tabs[0]:
            st.subheader("📊 Batch ID Results")
            
            # Metrics
            col1, col2, col3, col4 = st.columns(4)
            
            total_missing = len(results_df)
            found_count = len(results_df[results_df['Status'] == 'Found'])
            not_found_count = len(results_df[results_df['Status'] != 'Found'])
            success_rate = (found_count / total_missing * 100) if total_missing > 0 else 0
            
            with col1:
                st.metric("📋 Missing Batch", f"{total_missing:,}")
            with col2:
                st.metric("✅ Found", f"{found_count:,}")
            with col3:
                st.metric("❌ Not Found", f"{not_found_count:,}")
            with col4:
                st.metric("📈 Success Rate", f"{success_rate:.1f}%")
            
            # Show results table
            st.write("**Results:**")
            st.dataframe(results_df, use_container_width=True)
            
            # Download section
            st.write("---")
            st.write("**📥 Download Options:**")
            
            col1, col2 = st.columns(2)
            
            # Download all results
            with col1:
                csv_buffer = io.StringIO()
                results_df.to_csv(csv_buffer, index=False)
                st.download_button(
                    label="📥 Download All Results",
                    data=csv_buffer.getvalue(),
                    file_name="batch_id_results_all.csv",
                    mime="text/csv"
                )
            
            # Download Distru import format (only found ones)
            with col2:
                found_df = results_df[results_df['Status'] == 'Found'][['ID', 'Batch ID']].copy()
                found_df.columns = ['ID', 'Distru Batch Number']
                
                if len(found_df) > 0:
                    csv_buffer = io.StringIO()
                    found_df.to_csv(csv_buffer, index=False)
                    st.download_button(
                        label="📥 Download Distru Import Format",
                        data=csv_buffer.getvalue(),
                        file_name="batch_id_distru_import.csv",
                        mime="text/csv",
                        help="Two-column format: ID and Distru Batch Number for Distru bulk import"
                    )
                else:
                    st.info("No Batch IDs found to export")
        
        # Packages Tab
        with tabs[1]:
            st.subheader("📦 Packages Data")
            if 'packages_df' in st.session_state:
                packages_df = st.session_state['packages_df']
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Packages", f"{len(packages_df):,}")
                with col2:
                    has_batch = packages_df['Distru Batch Number'].notna().sum()
                    st.metric("With Batch ID", f"{has_batch:,}")
                with col3:
                    missing = packages_df['Distru Batch Number'].isna().sum()
                    st.metric("Missing Batch ID", f"{missing:,}")
                
                # Show packages missing batch
                st.write("**Packages Missing Batch ID:**")
                missing_df = packages_df[packages_df['Distru Batch Number'].isna()][
                    ['ID', 'Package Label', 'Distru Product', 'Category', 'Distru Batch Number']
                ]
                st.dataframe(missing_df, use_container_width=True)
        
        # Assemblies Tab
        with tabs[2]:
            st.subheader("🔧 Assemblies Data")
            if 'assemblies_df' in st.session_state:
                assemblies_df = st.session_state['assemblies_df']
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Records", f"{len(assemblies_df):,}")
                with col2:
                    outputs = len(assemblies_df[assemblies_df['Input/Output'] == 'Output'])
                    st.metric("Output Records", f"{outputs:,}")
                with col3:
                    inputs = len(assemblies_df[assemblies_df['Input/Output'] == 'Input'])
                    st.metric("Input Records", f"{inputs:,}")
                
                st.write("**Sample Assembly Records:**")
                st.dataframe(
                    assemblies_df[['Assembly Number', 'Input/Output', 'Package Number', 'Batch Number', 'Distru Product']].head(20),
                    use_container_width=True
                )
    
    else:
        # Welcome screen
        st.info("👆 Upload both CSV files in the sidebar to get started")
        
        st.subheader("📋 How This Tool Works")
        
        st.markdown(f"""
        **🔍 Batch ID Finder v{VERSION}**
        
        This tool finds missing Batch IDs for Distru packages by cross-referencing assembly records.
        
        **📥 Required Inputs:**
        1. **Packages CSV** - Export from Distru Packages report
        2. **Assemblies CSV** - Export from Distru Assemblies report
        
        **🔧 Process:**
        1. Identifies packages with blank `Distru Batch Number`
        2. Finds each package's label in Assemblies (Output rows)
        3. Locates the corresponding Input row for that Assembly
        4. Extracts the Batch Number from the Input row
        
        **📤 Outputs:**
        - Full results with all matching details
        - Distru-ready import format (ID + Batch Number)
        """)
        
        with st.expander("📊 Column Mapping Reference"):
            st.markdown("""
            **Packages CSV Columns Used:**
            - `ID` - Distru Package ID
            - `Package Label` - METRC tag/label
            - `Distru Product` - Product name
            - `Distru Batch Number` - The field we're looking to populate
            
            **Assemblies CSV Columns Used:**
            - `Assembly Number` - Links Input and Output rows
            - `Input/Output` - Indicates row type
            - `Package Number` - METRC tag/label
            - `Batch Number` - The batch ID we're retrieving
            """)


if __name__ == "__main__":
    main()