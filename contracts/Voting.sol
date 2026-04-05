// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract Voting {
    struct Candidate {
        string name;
        uint256 voteCount;
    }

    string public electionName;
    uint256 public startTime;
    uint256 public endTime;
    bool public electionCreated;

    Candidate[] public candidates;
    mapping(address => bool) public isRegistered;
    mapping(address => bool) public hasVoted;
    uint256 public totalVoters;
    uint256 public totalVotes;

    function createElection(
        string memory name,
        uint256 start,
        uint256 end
    ) external {
        electionName = name;
        startTime = start;
        endTime = end;
        electionCreated = true;
    }

    function addCandidate(string memory name) external {
        candidates.push(Candidate({name: name, voteCount: 0}));
    }

    function registerVoter(address voter) external {
        if (!isRegistered[voter]) {
            isRegistered[voter] = true;
            totalVoters++;
        }
    }

    function castVote(uint256 candidateIndex) external {
        require(electionCreated, "Election not created");
        require(isRegistered[msg.sender], "Voter not registered");
        require(!hasVoted[msg.sender], "Already voted");
        require(candidateIndex < candidates.length, "Invalid candidate");
        if (startTime != 0 || endTime != 0) {
            require(block.timestamp >= startTime, "Election not started");
            require(block.timestamp <= endTime, "Election ended");
        }
        hasVoted[msg.sender] = true;
        candidates[candidateIndex].voteCount++;
        totalVotes++;
    }

    function getResults()
        external
        view
        returns (string[] memory names, uint256[] memory counts)
    {
        uint256 len = candidates.length;
        names = new string[](len);
        counts = new uint256[](len);
        for (uint256 i = 0; i < len; i++) {
            names[i] = candidates[i].name;
            counts[i] = candidates[i].voteCount;
        }
    }

    function getCandidate(uint256 idx)
        external
        view
        returns (string memory, uint256)
    {
        require(idx < candidates.length, "Invalid candidate");
        return (candidates[idx].name, candidates[idx].voteCount);
    }

    function candidateCount() external view returns (uint256) {
        return candidates.length;
    }
}
