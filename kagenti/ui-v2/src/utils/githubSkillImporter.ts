// Copyright 2026 IBM Corp.
// Licensed under the Apache License, Version 2.0

/**
 * GitHub Skill Importer Utility
 * 
 * This utility handles automatic skill import from GitHub URLs.
 * It parses GitHub URLs, fetches file contents recursively, and extracts
 * skill metadata from SKILL.md files.
 */

interface GitHubUrlParts {
  owner: string;
  repo: string;
  branch: string;
  path: string;
}

interface GitHubFile {
  name: string;
  path: string;
  type: 'file' | 'dir';
  download_url?: string;
  url: string;
}

interface SkillMetadata {
  name?: string;
  description?: string;
  category?: string;
}

export interface ImportedSkillData {
  name: string;
  description: string;
  category: string;
  skillMdContent: string;
  files: Array<{ path: string; content: string }>;
}

/**
 * Parse a GitHub URL to extract owner, repo, branch, and path
 * Supports formats:
 * - https://github.com/owner/repo/tree/branch/path/to/skill
 * - https://github.com/owner/repo/blob/branch/path/to/file
 */
export function parseGitHubUrl(url: string): GitHubUrlParts | null {
  try {
    const urlObj = new URL(url);
    
    if (urlObj.hostname !== 'github.com') {
      return null;
    }

    const pathParts = urlObj.pathname.split('/').filter(Boolean);
    
    // Need at least: owner, repo, tree/blob, branch
    if (pathParts.length < 4) {
      return null;
    }

    const owner = pathParts[0];
    const repo = pathParts[1];
    const type = pathParts[2]; // 'tree' or 'blob'

    if (type !== 'tree' && type !== 'blob') {
      return null;
    }

    // For branch names with slashes (e.g., feature/add-skill-loading-support),
    // we need to determine where the branch ends and the path begins.
    // Strategy: Try progressively longer branch names starting from the end,
    // since paths are more likely to have multiple segments than branch names.
    const remainingParts = pathParts.slice(3);
    
    // Start with the assumption that everything except the last part is the branch
    // and work backwards. This handles cases like:
    // - feature/add-skill-loading-support/skills/summarizer
    //   -> branch: feature/add-skill-loading-support, path: skills/summarizer
    // - main/skills/summarizer
    //   -> branch: main, path: skills/summarizer
    
    let branch = '';
    let path = '';
    
    // Try from longest possible branch name to shortest
    for (let i = remainingParts.length - 1; i >= 0; i--) {
      const potentialBranch = remainingParts.slice(0, i + 1).join('/');
      const potentialPath = remainingParts.slice(i + 1).join('/');
      
      // If we have a path, this is a valid split
      // (we need at least one path segment for a skill directory)
      if (potentialPath) {
        branch = potentialBranch;
        path = potentialPath;
        break;
      }
    }
    
    // Fallback: if no path found, assume first part is branch and rest is path
    if (!branch) {
      branch = remainingParts[0];
      path = remainingParts.slice(1).join('/');
    }

    return { owner, repo, branch, path };
  } catch {
    return null;
  }
}

/**
 * Fetch file content from GitHub raw URL
 */
async function fetchFileContent(downloadUrl: string): Promise<string> {
  const response = await fetch(downloadUrl);
  if (!response.ok) {
    throw new Error(`Failed to fetch file: ${response.statusText}`);
  }
  return response.text();
}

/**
 * Fetch directory contents from GitHub API
 */
async function fetchDirectoryContents(
  owner: string,
  repo: string,
  path: string,
  branch: string
): Promise<GitHubFile[]> {
  const apiUrl = `https://api.github.com/repos/${owner}/${repo}/contents/${path}?ref=${branch}`;
  
  const response = await fetch(apiUrl, {
    headers: {
      'Accept': 'application/vnd.github.v3+json',
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to fetch directory: ${response.status} ${response.statusText}. ${errorText}`);
  }

  // Check rate limit headers
  const remaining = response.headers.get('X-RateLimit-Remaining');
  const limit = response.headers.get('X-RateLimit-Limit');
  
  if (remaining && limit) {
    const remainingNum = parseInt(remaining, 10);
    const limitNum = parseInt(limit, 10);
    
    // Warn when approaching rate limit (less than 20% remaining)
    if (remainingNum < limitNum * 0.2) {
      console.warn(
        `GitHub API rate limit warning: ${remainingNum}/${limitNum} requests remaining. ` +
        `Unauthenticated requests are limited to 60/hour. ` +
        `Consider using a GitHub token for higher limits (5000/hour).`
      );
    }
  }

  return response.json();
}

/**
 * Cache for successful branch/path lookups to reduce API calls
 * Key format: "owner/repo/branch/path"
 */
const branchPathCache = new Map<string, { branch: string; path: string }>();

/**
 * Try to find the correct branch/path split by testing against GitHub API
 * Uses session-based caching to minimize redundant API calls
 */
async function findValidBranchAndPath(
  owner: string,
  repo: string,
  remainingParts: string[]
): Promise<{ branch: string; path: string } | null> {
  // Check cache first
  const cacheKey = `${owner}/${repo}/${remainingParts.join('/')}`;
  const cached = branchPathCache.get(cacheKey);
  if (cached) {
    console.debug(`Using cached branch/path for ${cacheKey}`);
    return cached;
  }

  // Try progressively longer branch names, starting from shortest
  // This is more efficient as most branches don't have slashes
  for (let i = 0; i < remainingParts.length; i++) {
    const potentialBranch = remainingParts.slice(0, i + 1).join('/');
    const potentialPath = remainingParts.slice(i + 1).join('/');
    
    // We need at least a path for a skill directory
    if (!potentialPath) {
      continue;
    }
    
    // Test if this branch/path combination works
    try {
      const testUrl = `https://api.github.com/repos/${owner}/${repo}/contents/${potentialPath}?ref=${potentialBranch}`;
      const response = await fetch(testUrl, {
        method: 'HEAD', // Use HEAD to avoid downloading content
        headers: {
          'Accept': 'application/vnd.github.v3+json',
        },
      });
      
      if (response.ok) {
        const result = { branch: potentialBranch, path: potentialPath };
        // Cache successful lookup
        branchPathCache.set(cacheKey, result);
        return result;
      }
    } catch {
      // Continue trying other combinations
      continue;
    }
  }
  
  return null;
}

/**
 * Parse YAML frontmatter from SKILL.md content
 */
function parseSkillMetadata(content: string): SkillMetadata {
  const metadata: SkillMetadata = {};
  
  // Match YAML frontmatter between --- markers
  const frontmatterMatch = content.match(/^---\s*\n([\s\S]*?)\n---/);
  
  if (frontmatterMatch) {
    const frontmatter = frontmatterMatch[1];
    
    // Simple YAML parsing for name, description, and category
    const nameMatch = frontmatter.match(/^name:\s*(.+)$/m);
    const descMatch = frontmatter.match(/^description:\s*(.+)$/m);
    const categoryMatch = frontmatter.match(/^category:\s*(.+)$/m);
    
    if (nameMatch) metadata.name = nameMatch[1].trim();
    if (descMatch) metadata.description = descMatch[1].trim();
    if (categoryMatch) metadata.category = categoryMatch[1].trim();
  }
  
  return metadata;
}

/**
 * Recursively fetch all files from a GitHub directory
 *
 * @param maxDepth Maximum recursion depth (default: 5)
 * @param maxFiles Maximum number of files to fetch (default: 100)
 */
async function fetchAllFiles(
  owner: string,
  repo: string,
  path: string,
  branch: string,
  basePath: string = '',
  currentDepth: number = 0,
  maxDepth: number = 5,
  maxFiles: number = 100,
  fileCount: { count: number } = { count: 0 }
): Promise<Array<{ path: string; content: string }>> {
  const files: Array<{ path: string; content: string }> = [];
  
  // Check depth limit
  if (currentDepth >= maxDepth) {
    console.warn(`Max depth ${maxDepth} reached at path: ${path}`);
    return files;
  }
  
  // Check file count limit
  if (fileCount.count >= maxFiles) {
    console.warn(`Max file count ${maxFiles} reached`);
    return files;
  }
  
  try {
    const contents = await fetchDirectoryContents(owner, repo, path, branch);
    
    for (const item of contents) {
      // Check file count limit before processing each item
      if (fileCount.count >= maxFiles) {
        console.warn(`Max file count ${maxFiles} reached`);
        break;
      }
      
      const relativePath = basePath ? `${basePath}/${item.name}` : item.name;
      
      if (item.type === 'file' && item.download_url) {
        // Fetch file content
        const content = await fetchFileContent(item.download_url);
        files.push({ path: relativePath, content });
        fileCount.count++;
      } else if (item.type === 'dir') {
        // Recursively fetch directory contents with incremented depth
        const subFiles = await fetchAllFiles(
          owner,
          repo,
          item.path,
          branch,
          relativePath,
          currentDepth + 1,
          maxDepth,
          maxFiles,
          fileCount
        );
        files.push(...subFiles);
      }
    }
  } catch (error) {
    console.error(`Error fetching files from ${path}:`, error);
    throw error;
  }
  
  return files;
}

/**
 * Import skill data from a GitHub URL
 *
 * This function:
 * 1. Parses the GitHub URL
 * 2. Fetches all files recursively from the specified path
 * 3. Looks for SKILL.md and extracts metadata
 * 4. Returns structured data ready for form population
 *
 * Note: Unauthenticated GitHub API requests are limited to 60/hour.
 * Skills with many files may exhaust this limit quickly.
 */
export async function importSkillFromGitHub(
  url: string
): Promise<ImportedSkillData> {
  // Parse the URL
  let urlParts = parseGitHubUrl(url);
  if (!urlParts) {
    throw new Error('Invalid GitHub URL. Expected format: https://github.com/owner/repo/tree/branch/path');
  }

  let { owner, repo, branch, path } = urlParts;

  console.info(
    'Importing skill from GitHub. Note: Unauthenticated API requests are limited to 60/hour. ' +
    'Large skills may require multiple requests.'
  );

  // If the initial parse might have an incorrect branch/path split (due to slashes in branch name),
  // try to find the correct split by testing against the GitHub API
  try {
    const urlObj = new URL(url);
    const pathParts = urlObj.pathname.split('/').filter(Boolean);
    const remainingParts = pathParts.slice(3); // After owner/repo/tree
    
    const validSplit = await findValidBranchAndPath(owner, repo, remainingParts);
    if (validSplit) {
      branch = validSplit.branch;
      path = validSplit.path;
      console.info(`Resolved branch: ${branch}, path: ${path}`);
    }
  } catch (error) {
    console.warn('Could not validate branch/path split, using parsed values:', error);
  }

  // Fetch all files recursively
  const allFiles = await fetchAllFiles(owner, repo, path, branch);

  if (allFiles.length === 0) {
    throw new Error('No files found at the specified GitHub URL');
  }

  // Find SKILL.md file
  const skillMdFile = allFiles.find(
    (f) => f.path.toLowerCase() === 'skill.md'
  );

  if (!skillMdFile) {
    throw new Error('SKILL.md file not found in the specified directory');
  }

  // Parse metadata from SKILL.md
  const metadata = parseSkillMetadata(skillMdFile.content);

  // Prepare the result
  const result: ImportedSkillData = {
    name: metadata.name || '',
    description: metadata.description || '',
    category: metadata.category || '',
    skillMdContent: skillMdFile.content,
    files: allFiles.filter((f) => f.path.toLowerCase() !== 'skill.md'),
  };

  return result;
}

/**
 * Validate if a string is a valid GitHub URL
 */
export function isValidGitHubUrl(url: string): boolean {
  return parseGitHubUrl(url) !== null;
}

