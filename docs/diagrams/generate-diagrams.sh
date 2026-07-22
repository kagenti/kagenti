#!/bin/bash
# generate-diagrams.sh - Batch generate all Mermaid diagrams

echo "🎨 Generating Rossoctl Identity & Authentication Flow Diagrams..."
echo "=================================================="

# Check if mermaid-cli is installed
if ! command -v mmdc &> /dev/null; then
    echo "❌ mermaid-cli is not installed."
    echo "💡 Install it with: npm install -g @mermaid-js/mermaid-cli"
    echo "📖 Or visit: https://mermaid.live for online generation"
    exit 1
fi

# Create output directories
mkdir -p images/png
mkdir -p images/svg

# Counter for processed files
count=0

# Process all .mmd files
for mmd_file in *.mmd; do
    if [ -f "$mmd_file" ]; then
        base_name="${mmd_file%.mmd}"
        echo "🔄 Processing: $mmd_file"
        
        # Generate PNG (for documentation embedding)
        if mmdc -i "$mmd_file" -o "images/png/${base_name}.png" --quiet; then
            echo "   ✅ PNG: images/png/${base_name}.png"
        else
            echo "   ❌ Failed to generate PNG for $mmd_file"
        fi
        
        # Generate SVG (vector format for presentations)
        if mmdc -i "$mmd_file" -o "images/svg/${base_name}.svg" --quiet; then
            echo "   ✅ SVG: images/svg/${base_name}.svg"
        else
            echo "   ❌ Failed to generate SVG for $mmd_file"
        fi
        
        echo "   📐 Dimensions: $(identify -format "%wx%h" "images/png/${base_name}.png" 2>/dev/null || echo "N/A")"
        echo ""
        
        ((count++))
    fi
done

echo "=================================================="
echo "🎉 Successfully processed $count Mermaid diagrams!"
echo ""
echo "📁 Generated files:"
echo "   📊 PNG images: docs/diagrams/images/png/"
echo "   🎨 SVG images: docs/diagrams/images/svg/"
echo ""
echo "💡 Usage tips:"
echo "   • Use PNG files for embedding in markdown documentation"
echo "   • Use SVG files for presentations and high-quality prints"
echo "   • View diagrams online at: https://mermaid.live"
echo ""
echo "📚 Next steps:"
echo "   • Update documentation to reference generated images"  
echo "   • Commit images to repository for GitHub rendering"
echo "   • Consider adding diagrams to presentations/slides"
