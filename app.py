"""
Batch ID Finder v1.1.0
Find missing Batch IDs by cross-referencing Distru Packages with Assemblies or Manifest exports

Two modes:
1. Child Packages - For packages created via assembly/repackaging
   - Uses Assemblies export to find batch via Input row lookup
   
2. New Packages - For packages received on new manifests
   - Uses Manifest export from dc-receiving app to get Production Batch

CHANGELOG:
v1.1.0 (2025-01-30)
- Added "New Packages" mode for manifest-based batch lookup
- Added Expiration Date calculation (Lab Testing Updated Date + 1 year)
- Added mode selector at top of sidebar
- Enhanced output formats with Expiration Date

v1.0.0 (2025-01-26)
- Initial release with Child Packages mode
- Assemblies-based batch ID matching
"""

import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "1.1.0"

st.set_page_config(
    page_title=f"Batch ID Finder v{VERSION}",
    page_icon="🔍",
    layout="wide"
)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def calculate_expiration_date(lab_date_str):
    """
    Calculate expiration date by adding 1 year to lab testing date
    
    Args:
        lab_date_str: Date string in format YYYY-MM-DD or similar
        
    Returns:
        str: Expiration date in YYYY-MM-DD format, or None if invalid
    """
    if pd.isna(lab_date_str) or lab_date_str == '':
        return None
    
    try:
        # Parse the date (handles various formats)
        if isinstance(lab_date_str, str):
            # Try common formats
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%Y/%m/%d']:
                try:
                    lab_date = datetime.strptime(lab_date_str.split()[0], fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
        elif isinstance(lab_date_str, datetime):
            lab_date = lab_date_str
        elif hasattr(lab_date_str, 'date'):  # pandas Timestamp
            lab_date = lab_date_str.to_pydatetime()
        else:
            return None
        
        # Add 1 year
        expiration = lab_date + relativedelta(years=1)
        return expiration.strftime('%Y-%m-%d')
    except Exception:
        return None


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


def load_manifest_csv(uploaded_file):
    """
    Load Manifest export from dc-receiving app
    
    Args:
        uploaded_file: Streamlit uploaded file object
        
    Returns:
        tuple: (DataFrame, name) or (None, None) if error
    """
    try:
        df = pd.read_csv(uploaded_file, low_memory=False)
        return df, "Manifest"
    except Exception as e:
        st.error(f"Error loading Manifest CSV: {str(e)}")
        return None, None


# ============================================================================
# DATA PROCESSING FUNCTIONS - CHILD PACKAGES MODE
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


def find_batch_ids_child_packages(missing_batch_df, output_lookup, input_batch_lookup):
    """
    Find Batch IDs for packages missing them (Child Packages mode)
    
    Logic:
    1. Take Package Label from missing package
    2. Find it in output_lookup to get Assembly Number
    3. Use Assembly Number in input_batch_lookup to get Batch ID
    4. Calculate Expiration Date from Lab Testing Updated Date + 1 year
    
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
        lab_date = row.get('Lab Testing Updated Date')
        
        # Calculate expiration date
        expiration_date = calculate_expiration_date(lab_date)
        
        # Initialize result
        result = {
            'Distru Product': distru_product,
            'Package Label': package_label,
            'ID': distru_id,
            'Batch ID': None,
            'Expiration Date': expiration_date,
            'Lab Testing Date': lab_date,
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
# DATA PROCESSING FUNCTIONS - NEW PACKAGES MODE
# ============================================================================

def build_manifest_lookup(manifest_df):
    """
    Build lookup dictionary from manifest Package ID to Production Batch
    
    Note: Manifest Package ID doesn't have the leading "1" that Package Label has
    
    Args:
        manifest_df: Manifest DataFrame from dc-receiving
        
    Returns:
        dict: Package Label -> Production Batch mapping
    """
    if manifest_df is None or manifest_df.empty:
        return {}
    
    required_cols = ['Package ID', 'Production Batch']
    missing_cols = [col for col in required_cols if col not in manifest_df.columns]
    if missing_cols:
        st.error(f"❌ Missing columns in Manifest CSV: {', '.join(missing_cols)}")
        return {}
    
    # Build lookup: Add "1" prefix to Package ID to match Package Label format
    lookup = {}
    for _, row in manifest_df.iterrows():
        pkg_id = row['Package ID']
        batch = row['Production Batch']
        if pd.notna(pkg_id) and pd.notna(batch):
            # Convert Package ID to Package Label format by adding "1" prefix
            package_label = '1' + str(pkg_id)
            lookup[package_label] = batch
    
    return lookup


def find_batch_ids_new_packages(missing_batch_df, manifest_lookup):
    """
    Find Batch IDs for packages missing them (New Packages mode)
    
    Logic:
    1. Take Package Label from missing package
    2. Find it in manifest_lookup to get Production Batch
    3. Calculate Expiration Date from Lab Testing Updated Date + 1 year
    
    Args:
        missing_batch_df: Packages missing batch IDs
        manifest_lookup: Package Label -> Production Batch mapping
        
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
        lab_date = row.get('Lab Testing Updated Date')
        
        # Calculate expiration date
        expiration_date = calculate_expiration_date(lab_date)
        
        # Initialize result
        result = {
            'Distru Product': distru_product,
            'Package Label': package_label,
            'ID': distru_id,
            'Batch ID': None,
            'Expiration Date': expiration_date,
            'Lab Testing Date': lab_date,
            'Status': 'Not Found'
        }
        
        if pd.isna(package_label):
            result['Status'] = 'Missing Package Label'
            results.append(result)
            continue
        
        # Find Production Batch from manifest lookup
        batch_id = manifest_lookup.get(package_label)
        
        if batch_id is None:
            result['Status'] = 'Package not found in Manifest'
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
    st.markdown("Find missing Batch IDs by cross-referencing Distru Packages with Assemblies or Manifest exports")
    
    # ========================================================================
    # SIDEBAR
    # ========================================================================
    
    st.sidebar.header("⚙️ Mode Selection")
    
    mode = st.sidebar.radio(
        "Select batch lookup mode:",
        options=["Child Packages", "New Packages"],
        help="""
        **Child Packages**: For packages created via assembly/repackaging. Uses Assemblies export.
        
        **New Packages**: For packages received on manifests. Uses Manifest export from dc-receiving app.
        """
    )
    
    st.sidebar.markdown("---")
    st.sidebar.header("📊 Data Sources")
    
    # Common: Packages CSV upload
    st.sidebar.subheader("📦 Packages CSV")
    packages_file = st.sidebar.file_uploader(
        "Upload Distru Packages Export:",
        type=['csv'],
        key="packages",
        help="Export from Distru: Packages report"
    )
    
    # Mode-specific file upload
    if mode == "Child Packages":
        st.sidebar.subheader("🔧 Assemblies CSV")
        secondary_file = st.sidebar.file_uploader(
            "Upload Distru Assemblies Export:",
            type=['csv'],
            key="assemblies",
            help="Export from Distru: Assemblies report"
        )
        secondary_label = "Assemblies"
    else:  # New Packages
        st.sidebar.subheader("📋 Manifest CSV")
        secondary_file = st.sidebar.file_uploader(
            "Upload Manifest from dc-receiving:",
            type=['csv'],
            key="manifest",
            help="Export from dc-receiving app: Manifest packages"
        )
        secondary_label = "Manifest"
    
    # Process button
    ready_to_process = packages_file is not None and secondary_file is not None
    
    if st.sidebar.button("🚀 Find Batch IDs", type="primary", disabled=not ready_to_process):
        with st.spinner("Processing data..."):
            
            # Store mode in session state
            st.session_state['mode'] = mode
            
            # Load Packages
            st.info("📦 Loading Packages CSV...")
            packages_df, _ = load_packages_csv(packages_file)
            
            if packages_df is not None:
                st.session_state['packages_df'] = packages_df
                st.success(f"✅ Loaded {len(packages_df):,} packages")
            else:
                st.error("❌ Failed to load Packages CSV")
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
            
            # Mode-specific processing
            if mode == "Child Packages":
                # Load Assemblies
                st.info("🔧 Loading Assemblies CSV...")
                assemblies_df, _ = load_assemblies_csv(secondary_file)
                
                if assemblies_df is not None:
                    st.session_state['secondary_df'] = assemblies_df
                    st.success(f"✅ Loaded {len(assemblies_df):,} assembly records")
                else:
                    st.error("❌ Failed to load Assemblies CSV")
                    return
                
                # Build assembly lookups
                st.info("🔗 Building assembly lookups...")
                output_lookup, input_batch_lookup = build_assembly_lookup(assemblies_df)
                st.info(f"📊 Indexed {len(output_lookup):,} output packages and {len(input_batch_lookup):,} input batches")
                
                # Find batch IDs
                st.info("🎯 Matching packages to Batch IDs...")
                results_df = find_batch_ids_child_packages(missing_batch_df, output_lookup, input_batch_lookup)
                
            else:  # New Packages mode
                # Load Manifest
                st.info("📋 Loading Manifest CSV...")
                manifest_df, _ = load_manifest_csv(secondary_file)
                
                if manifest_df is not None:
                    st.session_state['secondary_df'] = manifest_df
                    st.success(f"✅ Loaded {len(manifest_df):,} manifest records")
                else:
                    st.error("❌ Failed to load Manifest CSV")
                    return
                
                # Build manifest lookup
                st.info("🔗 Building manifest lookup...")
                manifest_lookup = build_manifest_lookup(manifest_df)
                st.info(f"📊 Indexed {len(manifest_lookup):,} manifest packages")
                
                # Find batch IDs
                st.info("🎯 Matching packages to Batch IDs...")
                results_df = find_batch_ids_new_packages(missing_batch_df, manifest_lookup)
            
            if results_df is not None:
                st.session_state['results_df'] = results_df
                
                found_count = len(results_df[results_df['Status'] == 'Found'])
                not_found_count = len(results_df[results_df['Status'] != 'Found'])
                
                st.success(f"🎉 Processing complete! Found {found_count:,} Batch IDs, {not_found_count:,} not found")
    
    # Changelog
    with st.sidebar.expander("📋 Version History & Changelog"):
        st.markdown("""
        **v1.1.0** (Current - 2025-01-30)
        - 🆕 Added "New Packages" mode for manifest lookup
        - 📅 Added Expiration Date (Lab Date + 1 year)
        - ⚙️ Mode selector for Child vs New Packages
        - 📥 Enhanced export formats
        
        **v1.0.0** (2025-01-26)
        - 🆕 Initial release
        - 📦 Child Packages mode with Assemblies lookup
        """)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Version {VERSION}**")
    
    # ========================================================================
    # MAIN CONTENT
    # ========================================================================
    
    if 'results_df' in st.session_state and st.session_state['results_df'] is not None:
        results_df = st.session_state['results_df']
        current_mode = st.session_state.get('mode', 'Child Packages')
        
        # Create tabs
        tab_names = ["📊 Results", "📦 Packages"]
        if current_mode == "Child Packages":
            tab_names.append("🔧 Assemblies")
        else:
            tab_names.append("📋 Manifest")
        
        tabs = st.tabs(tab_names)
        
        # Results Tab
        with tabs[0]:
            st.subheader(f"📊 Batch ID Results ({current_mode} Mode)")
            
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
            
            col1, col2, col3 = st.columns(3)
            
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
                found_df = results_df[results_df['Status'] == 'Found'][['ID', 'Batch ID', 'Expiration Date']].copy()
                found_df.columns = ['ID', 'Distru Batch Number', 'Expiration Date']
                
                if len(found_df) > 0:
                    csv_buffer = io.StringIO()
                    found_df.to_csv(csv_buffer, index=False)
                    st.download_button(
                        label="📥 Distru Import (with Expiration)",
                        data=csv_buffer.getvalue(),
                        file_name="batch_id_distru_import.csv",
                        mime="text/csv",
                        help="Three-column format: ID, Distru Batch Number, Expiration Date"
                    )
                else:
                    st.info("No Batch IDs found")
            
            # Download minimal format (ID + Batch only)
            with col3:
                found_df_minimal = results_df[results_df['Status'] == 'Found'][['ID', 'Batch ID']].copy()
                found_df_minimal.columns = ['ID', 'Distru Batch Number']
                
                if len(found_df_minimal) > 0:
                    csv_buffer = io.StringIO()
                    found_df_minimal.to_csv(csv_buffer, index=False)
                    st.download_button(
                        label="📥 Distru Import (Batch Only)",
                        data=csv_buffer.getvalue(),
                        file_name="batch_id_distru_import_minimal.csv",
                        mime="text/csv",
                        help="Two-column format: ID, Distru Batch Number"
                    )
                else:
                    st.info("No Batch IDs found")
        
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
                display_cols = ['ID', 'Package Label', 'Distru Product', 'Category', 'Lab Testing Updated Date', 'Distru Batch Number']
                display_cols = [c for c in display_cols if c in packages_df.columns]
                missing_df = packages_df[packages_df['Distru Batch Number'].isna()][display_cols]
                st.dataframe(missing_df, use_container_width=True)
        
        # Secondary data tab (Assemblies or Manifest)
        with tabs[2]:
            if current_mode == "Child Packages":
                st.subheader("🔧 Assemblies Data")
                if 'secondary_df' in st.session_state:
                    assemblies_df = st.session_state['secondary_df']
                    
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
                st.subheader("📋 Manifest Data")
                if 'secondary_df' in st.session_state:
                    manifest_df = st.session_state['secondary_df']
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Total Packages", f"{len(manifest_df):,}")
                    with col2:
                        has_batch = manifest_df['Production Batch'].notna().sum()
                        st.metric("With Production Batch", f"{has_batch:,}")
                    
                    st.write("**Manifest Packages:**")
                    display_cols = ['Package #', 'Package ID', 'Item Name', 'Production Batch', 'Qty Shipped']
                    display_cols = [c for c in display_cols if c in manifest_df.columns]
                    st.dataframe(manifest_df[display_cols], use_container_width=True)
    
    else:
        # Welcome screen
        st.info("👆 Select a mode and upload the required files in the sidebar to get started")
        
        st.subheader("📋 How This Tool Works")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("""
            ### 👶 Child Packages Mode
            
            For packages created via **assembly/repackaging**.
            
            **Required Files:**
            1. **Packages CSV** - Distru Packages export
            2. **Assemblies CSV** - Distru Assemblies export
            
            **Process:**
            1. Find packages with blank Distru Batch Number
            2. Look up Package Label in Assemblies (Output rows)
            3. Get Assembly Number, find corresponding Input row
            4. Extract Batch Number from Input row
            5. Calculate Expiration Date (Lab Date + 1 year)
            """)
        
        with col2:
            st.markdown("""
            ### 📦 New Packages Mode
            
            For packages received on **new manifests**.
            
            **Required Files:**
            1. **Packages CSV** - Distru Packages export
            2. **Manifest CSV** - Export from dc-receiving app
            
            **Process:**
            1. Find packages with blank Distru Batch Number
            2. Match Package Label to Manifest Package ID
            3. Get Production Batch from manifest
            4. Calculate Expiration Date (Lab Date + 1 year)
            """)
        
        st.markdown("---")
        
        st.markdown(f"""
        **📤 Output Formats:**
        - **All Results** - Complete data with status and helper columns
        - **Distru Import (with Expiration)** - ID, Distru Batch Number, Expiration Date
        - **Distru Import (Batch Only)** - ID, Distru Batch Number
        """)


if __name__ == "__main__":
    main()