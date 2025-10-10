#!/usr/bin/env python3
"""Streamlit app to visualize parent-child chunking relationships."""

import streamlit as st
import pandas as pd
import json
from pathlib import Path
import tempfile
import os
from typing import List, Dict, Any

# Add the current directory to the path for imports
import sys
sys.path.insert(0, str(Path.cwd()))

try:
    from parent_child_document_chunker import DocumentChunker, ChunkingConfig
    CHUNKER_AVAILABLE = True
except ImportError:
    CHUNKER_AVAILABLE = False
    st.error("Document chunker not available. Please ensure the module is properly installed.")

# Page configuration
st.set_page_config(
    page_title="Parent-Child Chunker Visualizer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .chunk-card {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    .chunk-card:hover {
        background-color: #e9ecef;
        border-color: #1f77b4;
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .chunk-card.selected {
        background-color: #1f77b4;
        color: white;
        border-color: #1f77b4;
    }
    .stats-container {
        background-color: #f1f3f4;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .child-chunk {
        background-color: #ffffff;
        border: 1px solid #dee2e6;
        border-radius: 6px;
        padding: 0.75rem;
        margin: 0.5rem 0;
        border-left: 4px solid #28a745;
    }
    .parent-chunk {
        background-color: #ffffff;
        border: 1px solid #dee2e6;
        border-radius: 6px;
        padding: 0.75rem;
        margin: 0.5rem 0;
        border-left: 4px solid #007bff;
    }
    .metadata-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 10px;
        padding: 1rem;
        margin: 0.5rem 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .content-box {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white;
        border-radius: 10px;
        padding: 1rem;
        margin: 0.5rem 0;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .section-header {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        color: white;
        border-radius: 8px;
        padding: 0.75rem;
        margin: 1rem 0 0.5rem 0;
        text-align: center;
        font-weight: bold;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

def create_chunker_config() -> ChunkingConfig:
    """Create chunker configuration with user settings."""
    return ChunkingConfig(
        child_token_limit=st.sidebar.slider("Child Token Limit", 200, 800, 300, 50),
        child_overlap_tokens=st.sidebar.slider("Overlap Tokens", 20, 100, 50, 10),
        min_chunk_tokens=st.sidebar.slider("Min Chunk Tokens", 30, 150, 50, 10),
        enable_progress=False,
        save_chunks_to_files=False
    )

def process_markdown_file(uploaded_file) -> Dict[str, Any]:
    """Process uploaded markdown file and return chunking results."""
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as tmp_file:
            tmp_file.write(uploaded_file.getvalue().decode('utf-8'))
            tmp_path = tmp_file.name
        
        # Process with chunker
        config = create_chunker_config()
        chunker = DocumentChunker(config)
        result = chunker.chunk_file(tmp_path)
        
        # Store the temporary file path for content extraction
        result.source_path = tmp_path
        
        return {
            'success': True,
            'result': result,
            'config': config,
            'temp_file_path': tmp_path
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def display_chunk_stats(result) -> None:
    """Display chunking statistics."""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Parent Chunks", result.total_parents)
    
    with col2:
        st.metric("Child Chunks", result.total_children)
    
    with col3:
        avg_children = result.total_children / result.total_parents if result.total_parents > 0 else 0
        st.metric("Avg Children/Parent", f"{avg_children:.1f}")
    
    with col4:
        if result.pdf_stem:
            st.metric("Document", result.pdf_stem)
        else:
            st.metric("Document", "Unknown")

def display_parent_chunks(parent_chunks: List, selected_parent_id: str = None) -> str:
    """Display parent chunks in the left sidebar and return selected ID."""
    st.sidebar.markdown("## 📋 Parent Chunks")
    
    # Search/filter parent chunks
    search_term = st.sidebar.text_input("🔍 Search parent chunks:", "")
    
    filtered_parents = parent_chunks
    if search_term:
        filtered_parents = [p for p in parent_chunks if search_term.lower() in p.metadata["header"].lower()]
    
    st.sidebar.markdown(f"**Showing {len(filtered_parents)} of {len(parent_chunks)} parent chunks**")
    
    # Display parent chunks
    for i, parent in enumerate(filtered_parents):
        is_selected = parent.metadata["chunk_id"] == selected_parent_id
        
        # Create card content
        card_content = f"""
        <div class="chunk-card {'selected' if is_selected else ''}">
            <h4>{parent.metadata['header'][:50]}{'...' if len(parent.metadata['header']) > 50 else ''}</h4>
            <p><strong>Level:</strong> {parent.metadata['header_level']}</p>
            <p><strong>Tokens:</strong> {parent.metadata['token_count']}</p>
            <p><strong>Lines:</strong> {parent.metadata['start_line']}-{parent.metadata['end_line']}</p>
            <p><strong>Section:</strong> {parent.metadata['section_path'][:60]}{'...' if len(parent.metadata['section_path']) > 60 else ''}</p>
        </div>
        """
        
        # Make clickable with new label format
        if st.sidebar.button(f"Parent Chunk {i+1}", key=f"parent_{parent.metadata['chunk_id']}", use_container_width=True):
            st.session_state.selected_parent_id = parent.metadata["chunk_id"]
            st.rerun()
    
    return selected_parent_id

def display_parent_chunk_details(parent_chunk, child_chunks: List, source_path: str) -> None:
    """Display detailed parent chunk information on the left side."""
    st.markdown(f'<div class="section-header">📖 Parent Chunk: {parent_chunk.metadata["header"]}</div>', unsafe_allow_html=True)
    
    # Find children for this parent
    children = [c for c in child_chunks if c.metadata.get("parent_chunk_id") == parent_chunk.metadata["chunk_id"]]
    
    # Metadata Information Section
    st.markdown("### 🔧 Metadata Information")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<div class="metadata-box">', unsafe_allow_html=True)
        st.markdown(f"**Parent Chunk ID:** {parent_chunk.metadata['chunk_id']}")
        st.markdown(f"**Source Doc ID:** {parent_chunk.metadata['parent_doc_id']}")
        st.markdown(f"**Header Level:** {parent_chunk.metadata['header_level']}")
        st.markdown("</div>", unsafe_allow_html=True)
    
    with col2:
        st.markdown('<div class="metadata-box">', unsafe_allow_html=True)
        st.markdown(f"**Section Path:** {parent_chunk.metadata['section_path']}")
        st.markdown(f"**Lines:** {parent_chunk.metadata['start_line']} - {parent_chunk.metadata['end_line']}")
        st.markdown(f"**Token Count:** {parent_chunk.metadata['token_count']}")
        st.markdown(f"**Child Count:** {len(children)}")
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Page Content Section
    st.markdown("### 📄 Page Content")
    st.markdown('<div class="content-box">', unsafe_allow_html=True)
    
    # Show actual content from Document object with smart truncation for parents
    if parent_chunk.page_content:
        content = parent_chunk.page_content
        if len(content) > 200:  # Only truncate if content is longer than 200 chars
            first_part = content[:100]
            last_part = content[-100:]
            st.text(f"{first_part}...\n\n[Content truncated - {len(content)} total characters]\n\n...{last_part}")
        else:
            st.text(content)
    else:
        st.markdown(f"**Section:** {parent_chunk.metadata['section_path']}")
        st.markdown(f"**Header:** {parent_chunk.metadata['header']}")
        st.markdown("**Content:** No content available")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Child Chunks Summary
    if children:
        st.markdown("### 🔍 Child Chunks Summary")
        child_tokens = [c.metadata.get('token_count', 0) for c in children if c.metadata.get('token_count')]
        if child_tokens:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Children", len(children))
            with col2:
                st.metric("Avg Tokens", f"{sum(child_tokens)/len(child_tokens):.1f}")
            with col3:
                st.metric("Min Tokens", min(child_tokens))
            with col4:
                st.metric("Max Tokens", max(child_tokens))

def display_child_chunks(child_chunks: List, parent_id: str, parent_chunks: List, source_path: str) -> None:
    """Display child chunks for the selected parent on the right side."""
    # Find the parent chunk
    parent_chunk = next((p for p in parent_chunks if p.metadata["chunk_id"] == parent_id), None)
    if not parent_chunk:
        st.error("Parent chunk not found!")
        return
    
    # Find children for this parent
    children = [c for c in child_chunks if c.metadata.get("parent_chunk_id") == parent_id]
    
    if not children:
        st.warning("No child chunks found for this parent.")
        return
    
    st.markdown(f'<div class="section-header">🔍 Child Chunks ({len(children)} found)</div>', unsafe_allow_html=True)
    
    # Display each child chunk
    for i, child in enumerate(children):
        with st.expander(f"Child {i+1}: {child.metadata['header'][:60]}{'...' if len(child.metadata['header']) > 60 else ''}", expanded=False):
            # Child Metadata Information
            st.markdown("#### 🔧 Child Metadata")
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown('<div class="metadata-box">', unsafe_allow_html=True)
                st.markdown(f"**Chunk ID:** {child.metadata['chunk_id']}")
                st.markdown(f"**Parent Doc ID:** {child.metadata['parent_doc_id']}")
                st.markdown(f"**Parent Chunk ID:** {child.metadata.get('parent_chunk_id', 'None')}")
                st.markdown(f"**Token Count:** {child.metadata.get('token_count', 'N/A')}")
                st.markdown("</div>", unsafe_allow_html=True)
            
            with col2:
                st.markdown('<div class="metadata-box">', unsafe_allow_html=True)
                st.markdown(f"**Header:** {child.metadata['header']}")
                st.markdown(f"**Section Path:** {child.metadata['section_path']}")
                st.markdown(f"**Lines:** {child.metadata['start_line']} - {child.metadata['end_line']}")
                st.markdown(f"**Chunk Index:** {child.metadata.get('chunk_index', 'N/A')}")
                st.markdown("</div>", unsafe_allow_html=True)
            
            # Child Content Information
            st.markdown("#### 📄 Child Content")
            st.markdown('<div class="content-box">', unsafe_allow_html=True)
            
            # Show block types
            if child.metadata.get('block_types'):
                st.markdown(f"**Block Types:** {', '.join(child.metadata['block_types'])}")
            
            # Show actual content from Document object
            if child.page_content:
                st.text(child.page_content) # No truncation for child chunks
            else:
                st.markdown("**Content:** No content available")
            
            st.markdown("</div>", unsafe_allow_html=True)

def display_relationship_analysis(result) -> None:
    """Display relationship analysis between parent and child chunks."""
    st.markdown("## 🔗 Relationship Analysis")
    
    # Analyze relationships
    total_children = len(result.child_chunks)
    valid_parent_refs = sum(1 for c in result.child_chunks if c.metadata.get("parent_chunk_id"))
    valid_section_paths = sum(1 for c in result.child_chunks if c.metadata.get("section_path") and c.metadata["section_path"].strip())
    valid_token_counts = sum(1 for c in result.child_chunks if c.metadata.get('token_count') and c.metadata['token_count'] > 0)
    
    # Calculate integrity score
    integrity_score = (valid_parent_refs + valid_section_paths + valid_token_counts) / (total_children * 3) * 100
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Relationship Metrics:**")
        st.metric("Valid Parent References", f"{valid_parent_refs}/{total_children} ({valid_parent_refs/total_children*100:.1f}%)")
        st.metric("Valid Section Paths", f"{valid_section_paths}/{total_children} ({valid_section_paths/total_children*100:.1f}%)")
        st.metric("Valid Token Counts", f"{valid_token_counts}/{total_children} ({valid_token_counts/total_children*100:.1f}%)")
    
    with col2:
        st.markdown("**Overall Integrity:**")
        if integrity_score >= 95:
            st.success(f"🎯 EXCELLENT: {integrity_score:.1f}%")
        elif integrity_score >= 85:
            st.success(f"✅ GOOD: {integrity_score:.1f}%")
        elif integrity_score >= 70:
            st.warning(f"⚠️ FAIR: {integrity_score:.1f}%")
        else:
            st.error(f"❌ POOR: {integrity_score:.1f}%")
        
        # Check for orphaned children
        orphaned_children = [c for c in result.child_chunks if not c.metadata.get("parent_chunk_id")]
        if orphaned_children:
            st.warning(f"⚠️ Orphaned Children: {len(orphaned_children)}")
        else:
            st.success("✅ No Orphaned Children")
    
    # Visualize parent-child distribution
    st.markdown("**Parent-Child Distribution:**")
    parent_children_count = {}
    for parent in result.parent_chunks:
        children_count = len([c for c in result.child_chunks if c.metadata.get("parent_chunk_id") == parent.metadata["chunk_id"]])
        parent_children_count[parent.metadata["header"][:30] + "..." if len(parent.metadata["header"]) > 30 else parent.metadata["header"]] = children_count
    
    # Create a simple bar chart
    if parent_children_count:
        df = pd.DataFrame(list(parent_children_count.items()), columns=['Parent Chunk', 'Child Count'])
        st.bar_chart(df.set_index('Parent Chunk'))

def main():
    """Main Streamlit application."""
    st.markdown('<h1 class="main-header">🔍 Parent-Child Chunker Visualizer</h1>', unsafe_allow_html=True)
    
    if not CHUNKER_AVAILABLE:
        st.error("Document chunker module not available. Please check your installation.")
        return
    
    # Initialize session state
    if 'selected_parent_id' not in st.session_state:
        st.session_state.selected_parent_id = None
    if 'chunking_result' not in st.session_state:
        st.session_state.chunking_result = None
    if 'temp_file_path' not in st.session_state:
        st.session_state.temp_file_path = None
    
    # Clean up any existing temporary files
    if st.session_state.temp_file_path and os.path.exists(st.session_state.temp_file_path):
        try:
            os.unlink(st.session_state.temp_file_path)
            st.session_state.temp_file_path = None
        except:
            pass
    
    # Sidebar configuration
    st.sidebar.markdown("## ⚙️ Configuration")
    
    # File upload
    st.sidebar.markdown("## 📁 Upload Document")
    uploaded_file = st.sidebar.file_uploader(
        "Choose a markdown file (.md)",
        type=['md', 'markdown'],
        help="Upload an output.md file to process with the chunker"
    )
    
    if uploaded_file is not None:
        # Process the file
        if st.sidebar.button("🚀 Process Document", use_container_width=True):
            with st.spinner("Processing document..."):
                result = process_markdown_file(uploaded_file)
                if result['success']:
                    st.session_state.chunking_result = result
                    st.session_state.selected_parent_id = None
                    st.session_state.temp_file_path = result['temp_file_path'] # Store temp file path
                    st.success("Document processed successfully!")
                    st.rerun()
                else:
                    st.error(f"Error processing document: {result['error']}")
        
        # Display results if available
        if st.session_state.chunking_result:
            result = st.session_state.chunking_result['result']
            temp_file_path = st.session_state.chunking_result.get('temp_file_path')
            
            # Display chunking statistics
            display_chunk_stats(result)
            
            # Main content area - Restructured layout
            if st.session_state.selected_parent_id:
                # Two-column layout: Parent details on left, Child chunks on right
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    # Display parent chunk details on the left
                    display_parent_chunk_details(
                        next((p for p in result.parent_chunks if p.metadata["chunk_id"] == st.session_state.selected_parent_id), None),
                        result.child_chunks,
                        st.session_state.temp_file_path or result.source_path
                    )
                
                with col2:
                    # Display child chunks on the right
                    display_child_chunks(result.child_chunks, st.session_state.selected_parent_id, result.parent_chunks, st.session_state.temp_file_path or result.source_path)
            else:
                # Show instruction when no parent is selected
                st.info("👈 Select a parent chunk from the left sidebar to view its details and child chunks")
            
            # Display parent chunks in sidebar
            selected_parent_id = display_parent_chunks(
                result.parent_chunks, 
                st.session_state.selected_parent_id
            )
            
            # Relationship analysis
            st.markdown("---")
            display_relationship_analysis(result)
            
            # Export options
            st.markdown("---")
            st.markdown("## 💾 Export Options")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("📊 Export to JSON", use_container_width=True):
                    # Convert result to JSON
                    result_dict = result.to_dict()
                    st.download_button(
                        label="⬇️ Download JSON",
                        data=json.dumps(result_dict, indent=2),
                        file_name=f"chunked_document_{result.pdf_stem or 'unknown'}.json",
                        mime="application/json"
                    )
            
            with col2:
                if st.button("📋 Export Summary", use_container_width=True):
                    # Create summary
                    summary = {
                        "document_info": {
                            "source_path": result.source_path,
                            "pdf_stem": result.pdf_stem,
                            "total_parents": result.total_parents,
                            "total_children": result.total_children
                        },
                        "parent_chunks": [
                            {
                                "header": p.metadata["header"],
                                "header_level": p.metadata["header_level"],
                                "token_count": p.metadata["token_count"],
                                "section_path": p.metadata["section_path"]
                            } for p in result.parent_chunks
                        ]
                    }
                    
                    st.download_button(
                        label="⬇️ Download Summary",
                        data=json.dumps(summary, indent=2),
                        file_name=f"chunking_summary_{result.pdf_stem or 'unknown'}.json",
                        mime="application/json"
                    )
            
            # Clean up temporary file when session ends
            if st.session_state.temp_file_path and os.path.exists(st.session_state.temp_file_path):
                try:
                    os.unlink(st.session_state.temp_file_path)
                except:
                    pass  # Ignore cleanup errors
    
    else:
        # Welcome message
        st.markdown("""
        ## 🎯 Welcome to the Parent-Child Chunker Visualizer!
        
        This application allows you to:
        
        1. **Upload** a markdown file (like `output.md`)
        2. **Process** it with the document chunker
        3. **Explore** parent chunks in the left sidebar
        4. **View** parent chunk details on the left side
        5. **View** child chunks on the right side
        6. **Analyze** the relationships and integrity
        
        ### 📋 How to Use:
        
        1. **Upload** your markdown file using the sidebar
        2. **Configure** chunking parameters (token limits, overlap)
        3. **Process** the document
        4. **Click** on parent chunks to view their details and children
        5. **Explore** the hierarchical structure
        
        ### 🔍 What You'll See:
        
        - **Parent Chunks**: Major sections based on headers
        - **Child Chunks**: Smaller, searchable segments within sections
        - **Relationship Analysis**: Integrity metrics and validation
        - **Export Options**: Download results in various formats
        
        Start by uploading a markdown file! 🚀
        """)

if __name__ == "__main__":
    main()
